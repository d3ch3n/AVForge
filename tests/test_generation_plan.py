import copy
import json
import tempfile
import unittest
from pathlib import Path

from ingestion.extraction import build_extraction_result, make_evidence, make_fact
from ingestion.generation_plan import (
    GENERATION_PLAN_VERSION,
    assess_generation_plan,
    compare_generation_plans,
    make_input_bindings,
    make_plan,
    plan_id,
    read_generation_plan,
    validate_generation_plan,
    write_generation_plan,
)
from ingestion.mapping import build_mapping_result, make_mapping, make_semantic_bindings, make_target
from ingestion.unit_normalization import normalize_fact
from tests.test_unit_normalization import extraction_with, fact as normalization_fact


UNITS = {"kilogram", "milliampere", "ampere", "volt"}
VOCAB_BINDINGS = {"units": {"version": "1.1.0", "sha256": "sha256:units"}}
SCHEMA_CONTEXT = {"id": "https://avforge.local/schemas/equipment.schema.json", "version": "3.10", "sha256": "sha256:schema"}


def literal(value, **extra):
    return {"kind": "literal", "value": value, **extra}


def fixture_context():
    source = {
        "source_id": "source-fixture",
        "content_hash": "sha256:fixture",
        "tier": 1,
        "canonicality": "official-canonical",
        "source_type": "html",
        "final_url": "https://manufacturer.example/product",
    }
    evidence = make_evidence(
        source=source,
        locator={"kind": "html", "heading": "Mass"},
        observation="794 g",
        extraction_method="fixture",
    )
    fact = make_fact(
        subject={"kind": "equipment", "local_id": "acme.model-x"},
        property="mass",
        value=794,
        unit="g",
        evidence_ids=[evidence["evidence_id"]],
    )
    extraction = build_extraction_result(
        job_id="job-generation-fixture",
        identity={"manufacturer": "Acme", "canonical_model": "Model X", "identity_status": "RESOLVED"},
        sources=[source],
        facts=[fact],
        evidence=[evidence],
        observed_at="2026-01-01T00:00:00+00:00",
    )
    target = make_target(
        segments=[
            {"kind": "property", "name": "hardware"},
            {"kind": "property", "name": "weight"},
        ],
        schema_ref="#/$defs/hardware",
    )
    normalized = normalize_fact(
        fact,
        dimension="mass",
        canonical_unit="kilogram",
        canonical_unit_ids=UNITS,
    )
    mapping = make_mapping(
        fact_id=fact["fact_id"],
        evidence_ids=fact["evidence_ids"],
        state="STRUCTURED",
        target=target,
        semantic_bindings=make_semantic_bindings(fact, target=target, normalization=normalized),
    )
    mapping_result = build_mapping_result(
        extraction_result=extraction,
        mappings=[mapping],
        vocabularies={"units": UNITS},
        model_context={"schema": {"id": "schema", "title": "AVForge Equipment v3.10", "sha256": "sha256:schema"}},
        observed_at="2026-01-01T00:00:00+00:00",
    )
    identity = {"manufacturer": "Acme", "canonical_model": "Model X", "identity_status": "RESOLVED"}
    bindings = make_input_bindings(
        identity=identity,
        extraction_result=extraction,
        mapping_result=mapping_result,
        schema={"id": "https://avforge.local/schemas/equipment.schema.json", "version": "3.10", "sha256": "sha256:schema"},
        vocabularies=VOCAB_BINDINGS,
    )
    root = {
        "fields": {
            "id": literal("acme.model-x"),
            "manufacturer": {"kind": "identity", "path": ["manufacturer"]},
            "model": {"kind": "identity", "path": ["canonical_model"]},
            "product_name": literal("Model X"),
            "category": literal("fixture"),
            "schema_version": literal("3.10"),
            "status": literal("draft"),
        }
    }
    entity = {
        "entity_kind": "hardware",
        "entity_id": "hardware",
        "collection_target": make_target(segments=[{"kind": "property", "name": "hardware"}]),
    }
    operation = {
        "op": "SET_VALUE",
        "target": target,
        "value_source": {"kind": "normalized_binding", "mapping_id": mapping["mapping_id"], "path": ["normalization", "canonical_value"]},
    }
    return extraction, mapping_result, identity, bindings, root, entity, operation, fact, mapping


def make_fixture_plan(**kwargs):
    extraction, mapping, identity, bindings, root, entity, operation, fact, mapping_record = fixture_context()
    values = {
        "job_id": "job-generation-fixture",
        "input_bindings": bindings,
        "root": root,
        "entities": [entity],
        "operations": [operation],
        "extraction_result": extraction,
        "mapping_result": mapping,
        "vocabularies": {"units": UNITS},
    }
    values.update(kwargs)
    if values.get("operations") is None:
        values["operations"] = []
    return make_plan(**values)


def assess_fixture_plan(plan, **kwargs):
    extraction, mapping, identity = fixture_context()[:3]
    context = {
        "extraction_result": extraction,
        "mapping_result": mapping,
        "vocabularies": {"units": UNITS},
        "resolved_identity": identity,
        "schema_context": SCHEMA_CONTEXT,
        "vocabulary_context": VOCAB_BINDINGS,
    }
    context.update(kwargs)
    return assess_generation_plan(plan, **context)


def fixture_authoritative_context():
    extraction, mapping, identity = fixture_context()[:3]
    return {
        "extraction_result": extraction,
        "mapping_result": mapping,
        "vocabularies": {"units": UNITS},
        "resolved_identity": identity,
        "schema_context": SCHEMA_CONTEXT,
        "vocabulary_context": VOCAB_BINDINGS,
    }


class GenerationPlanModelTests(unittest.TestCase):
    def test_valid_version_and_root_sources(self):
        plan = make_fixture_plan()
        self.assertEqual(plan["generation_plan_version"], GENERATION_PLAN_VERSION)
        validate_generation_plan(plan, extraction_result=fixture_context()[0], mapping_result=fixture_context()[1], vocabularies={"units": UNITS})

    def test_unsupported_version_rejected(self):
        plan = make_fixture_plan()
        plan["generation_plan_version"] = "2.0"
        with self.assertRaises(ValueError):
            validate_generation_plan(plan)

    def test_plan_id_is_canonical_and_inputs_change_identity(self):
        plan = make_fixture_plan()
        reordered = json.loads(json.dumps(plan, sort_keys=False))
        reordered["root"]["fields"] = dict(reversed(list(reordered["root"]["fields"].items())))
        reordered["plan_id"] = plan_id(reordered)
        self.assertEqual(plan["plan_id"], reordered["plan_id"])

        changed = copy.deepcopy(plan)
        changed["operations"][0]["value_source"] = literal("0.795")
        self.assertNotEqual(plan["plan_id"], plan_id(changed))

        mapping_changed = copy.deepcopy(plan)
        mapping_changed["input_bindings"]["mapping"]["semantic_hash"] = "sha256:changed"
        self.assertNotEqual(plan["plan_id"], plan_id(mapping_changed))

        schema_changed = copy.deepcopy(plan)
        schema_changed["input_bindings"]["schema"]["sha256"] = "sha256:changed"
        self.assertNotEqual(plan["plan_id"], plan_id(schema_changed))

    def test_entity_declarations_coalesce_only_when_identical(self):
        plan = make_fixture_plan(entities=[fixture_context()[5], fixture_context()[5]])
        self.assertEqual(len(plan["entities"]), 2)
        conflicting = copy.deepcopy(fixture_context()[5])
        conflicting["entity_id"] = "other"
        conflicting["collection_target"] = make_target(segments=[{"kind": "property", "name": "interfaces"}])
        with self.assertRaises(ValueError):
            make_fixture_plan(entities=[fixture_context()[5], {**fixture_context()[5], "collection_target": conflicting["collection_target"]}])

    def test_invalid_target_and_unknown_operation_rejected(self):
        plan = make_fixture_plan()
        invalid = copy.deepcopy(plan)
        invalid["operations"][0]["target"]["segments"][0]["name"] = "interfaces[0]"
        invalid["plan_id"] = plan_id(invalid)
        with self.assertRaises(ValueError):
            validate_generation_plan(invalid, extraction_result=fixture_context()[0], mapping_result=fixture_context()[1], vocabularies={"units": UNITS})

        unknown = copy.deepcopy(plan)
        unknown["operations"][0]["op"] = "DELETE"
        with self.assertRaises(ValueError):
            validate_generation_plan(unknown, extraction_result=fixture_context()[0], mapping_result=fixture_context()[1], vocabularies={"units": UNITS})


class GenerationPlanAuthorizationTests(unittest.TestCase):
    def test_context_free_structural_plan_fails_closed(self):
        plan = make_fixture_plan(operations=[{"op": "SET_VALUE", "target": make_target(segments=[{"kind": "property", "name": "custom_fields"}]), "value_source": literal("fixture")}])
        result = assess_generation_plan(plan)
        self.assertTrue(result["valid"])
        self.assertFalse(result["generation_allowed"])
        self.assertTrue(result["publication_blocking"])
        self.assertEqual(result["authorization_errors"], ["MISSING_AUTHORITATIVE_CONTEXT:extraction,mapping,resolved_identity,schema,vocabularies"])

    def test_each_missing_authoritative_context_fails_closed(self):
        plan = make_fixture_plan(operations=[{"op": "SET_VALUE", "target": make_target(segments=[{"kind": "property", "name": "custom_fields"}]), "value_source": literal("fixture")}])
        context_names = {
            "extraction_result": "extraction",
            "mapping_result": "mapping",
            "resolved_identity": "resolved_identity",
            "schema_context": "schema",
            "vocabulary_context": "vocabularies",
        }
        for name in ("extraction_result", "mapping_result", "resolved_identity", "schema_context", "vocabularies"):
            context = fixture_authoritative_context()
            context.pop(name)
            if name == "vocabularies":
                context.pop("vocabulary_context")
            result = assess_generation_plan(plan, **context)
            self.assertTrue(result["valid"], name)
            self.assertFalse(result["generation_allowed"], name)
            self.assertTrue(result["publication_blocking"], name)
            self.assertTrue(result["authorization_errors"][0].startswith(f"MISSING_AUTHORITATIVE_CONTEXT:{context_names.get(name, 'vocabularies')}"), name)

    def test_each_mismatched_authoritative_context_fails_closed(self):
        plan = make_fixture_plan()
        for name in ("extraction_result", "mapping_result", "resolved_identity", "schema_context", "vocabulary_context"):
            context = fixture_authoritative_context()
            context[name] = copy.deepcopy(context[name])
            if name == "extraction_result":
                context[name]["semantic_hash"] = "sha256:wrong"
            elif name == "mapping_result":
                context[name]["semantic_hash"] = "sha256:wrong"
            elif name == "resolved_identity":
                context[name]["canonical_model"] = "Wrong Model"
            elif name == "schema_context":
                context[name]["sha256"] = "sha256:wrong"
            else:
                context[name]["units"]["sha256"] = "sha256:wrong"
            result = assess_generation_plan(plan, **context)
            self.assertFalse(result["generation_allowed"], name)
            self.assertTrue(result["publication_blocking"], name)
            self.assertTrue(result["authorization_errors"], name)

    def test_complete_authoritative_context_allows_generation(self):
        result = assess_fixture_plan(make_fixture_plan())
        self.assertTrue(result["valid"])
        self.assertTrue(result["generation_allowed"])
        self.assertFalse(result["publication_blocking"])

    def test_schema_gap_remains_structurally_valid_but_blocked(self):
        plan = make_fixture_plan(issues=[{
            "issue_id": "issue-schema-gap",
            "code": "SCHEMA_GAP",
            "source": {"kind": "fixture", "id": "fixture-issue"},
            "fact_ids": [],
            "mapping_ids": [],
            "reason": "fixture schema gap",
        }], operations=[])
        result = assess_fixture_plan(plan)
        self.assertTrue(result["valid"])
        self.assertFalse(result["generation_allowed"])

    def test_conflict_and_normalization_controls_remain_unchanged(self):
        context = fixture_context()
        conflict_plan = make_fixture_plan(issues=[{
            "issue_id": "issue-conflict",
            "code": "CONFLICT",
            "source": {"kind": "fixture", "id": "fixture-issue"},
            "fact_ids": [context[7]["fact_id"]],
            "mapping_ids": [context[8]["mapping_id"]],
            "reason": "fixture conflict",
        }], operations=[])
        conflict = assess_fixture_plan(conflict_plan)
        self.assertTrue(conflict["valid"])
        self.assertTrue(conflict["generation_allowed"])
        self.assertTrue(conflict["publication_blocking"])
        self.assertEqual(context[7]["value"], 794)
        self.assertEqual(normalize_fact(context[7], dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)["canonical_value"], "0.794")


class GenerationPlanValueTests(unittest.TestCase):
    def test_literal_fact_identity_and_normalized_sources(self):
        plan = make_fixture_plan()
        self.assertTrue(assess_fixture_plan(plan)["valid"])

        missing_fact = copy.deepcopy(plan)
        missing_fact["operations"][0]["value_source"] = {"kind": "fact", "fact_id": "missing", "path": ["value"]}
        missing_fact["plan_id"] = plan_id(missing_fact)
        with self.assertRaises(ValueError):
            validate_generation_plan(missing_fact, extraction_result=fixture_context()[0], mapping_result=fixture_context()[1], vocabularies={"units": UNITS})

        missing_path = copy.deepcopy(plan)
        missing_path["operations"][0]["value_source"] = {"kind": "fact", "fact_id": fixture_context()[7]["fact_id"], "path": ["value", "missing"]}
        missing_path["plan_id"] = plan_id(missing_path)
        with self.assertRaises(ValueError):
            validate_generation_plan(missing_path, extraction_result=fixture_context()[0], mapping_result=fixture_context()[1], vocabularies={"units": UNITS})

        missing_identity = copy.deepcopy(plan)
        missing_identity["root"]["fields"]["model"] = {"kind": "identity", "path": ["variant"]}
        missing_identity["plan_id"] = plan_id(missing_identity)
        with self.assertRaises(ValueError):
            validate_generation_plan(missing_identity, extraction_result=fixture_context()[0], mapping_result=fixture_context()[1], vocabularies={"units": UNITS})

    def test_normalized_binding_revalidates_mass(self):
        plan = make_fixture_plan()
        validate_generation_plan(plan, extraction_result=fixture_context()[0], mapping_result=fixture_context()[1], vocabularies={"units": UNITS})
        broken = copy.deepcopy(plan)
        broken["operations"][0]["value_source"]["path"] = ["normalization", "canonical_value", "missing"]
        broken["plan_id"] = plan_id(broken)
        with self.assertRaises(ValueError):
            validate_generation_plan(broken, extraction_result=fixture_context()[0], mapping_result=fixture_context()[1], vocabularies={"units": UNITS})

    def test_normalized_binding_accepts_current_conversions(self):
        for source_value, expected in ((300, "0.3"), (900, "0.9")):
            fact = normalization_fact(value=source_value, unit="milliampere", property_name="current")
            raw_extraction = extraction_with(fact)
            extraction = build_extraction_result(
                job_id=raw_extraction["job_id"],
                identity=raw_extraction["identity"],
                sources=raw_extraction["sources"],
                facts=raw_extraction["facts"],
                evidence=raw_extraction["evidence"],
                conflicts=raw_extraction["conflicts"],
                observed_at=raw_extraction["generated_at"],
            )
            target = make_target(segments=[{"kind": "property", "name": "custom_fields"}])
            normalized = normalize_fact(fact, dimension="current", canonical_unit="ampere", canonical_unit_ids=UNITS)
            mapping = make_mapping(
                fact_id=fact["fact_id"],
                evidence_ids=fact["evidence_ids"],
                state="STRUCTURED",
                target=target,
                semantic_bindings=make_semantic_bindings(fact, target=target, normalization=normalized),
            )
            mapping_result = build_mapping_result(extraction_result=extraction, mappings=[mapping], vocabularies={"units": UNITS}, observed_at="2026-01-01T00:00:00+00:00")
            identity = extraction["identity"]
            bindings = make_input_bindings(
                identity=identity,
                extraction_result=extraction,
                mapping_result=mapping_result,
                schema={"id": "schema", "version": "3.10", "sha256": "sha256:schema"},
                vocabularies=VOCAB_BINDINGS,
            )
            root = {"fields": {"id": literal("fixture.model"), "manufacturer": literal("Fixture"), "model": literal("Model"), "product_name": literal("Model"), "category": literal("fixture"), "schema_version": literal("3.10"), "status": literal("draft")}}
            plan = make_plan(
                job_id="job-fixture",
                input_bindings=bindings,
                root=root,
                operations=[{"op": "SET_VALUE", "target": target, "value_source": {"kind": "normalized_binding", "mapping_id": mapping["mapping_id"], "path": ["normalization", "canonical_value"]}}],
                extraction_result=extraction,
                mapping_result=mapping_result,
                vocabularies={"units": UNITS},
            )
            self.assertEqual(plan["operations"][0]["value_source"]["path"], ["normalization", "canonical_value"])
            self.assertEqual(expected, normalized["canonical_value"])

    def test_entity_reference_and_dangling_reference(self):
        plan = make_fixture_plan(
            operations=[
                {"op": "ADD_REFERENCE", "target": make_target(segments=[{"kind": "property", "name": "source_id"}]), "reference": {"entity_kind": "hardware", "entity_id": "hardware"}}
            ]
        )
        self.assertTrue(assess_fixture_plan(plan)["valid"])
        dangling = copy.deepcopy(plan)
        dangling["operations"][0]["reference"]["entity_id"] = "missing"
        dangling["plan_id"] = plan_id(dangling)
        with self.assertRaises(ValueError):
            validate_generation_plan(dangling)


class GenerationPlanMergeAndCollectionTests(unittest.TestCase):
    def test_identical_and_complementary_operations_are_allowed(self):
        target = make_target(segments=[{"kind": "property", "name": "hardware"}])
        plan = make_fixture_plan(
            operations=[
                {"op": "ENSURE_OBJECT", "target": target},
                {"op": "ENSURE_OBJECT", "target": target},
                {"op": "SET_VALUE", "target": make_target(segments=[{"kind": "property", "name": "hardware"}, {"kind": "property", "name": "weight"}]), "value_source": literal({"value": 1, "unit": "kilogram"})},
                {"op": "SET_VALUE", "target": make_target(segments=[{"kind": "property", "name": "hardware"}, {"kind": "property", "name": "form_factor"}]), "value_source": literal("desktop")},
            ]
        )
        self.assertTrue(assess_fixture_plan(plan)["valid"])

    def test_contradictory_scalar_write_rejected(self):
        target = make_target(segments=[{"kind": "property", "name": "model"}])
        with self.assertRaises(ValueError):
            make_fixture_plan(operations=[
                {"op": "SET_VALUE", "target": target, "value_source": literal("A")},
                {"op": "SET_VALUE", "target": target, "value_source": literal("B")},
            ])

    def test_duplicate_references_coalesce_and_scalar_collision_rejects(self):
        target = make_target(segments=[{"kind": "property", "name": "references"}])
        plan = make_fixture_plan(operations=[
            {"op": "ADD_REFERENCE", "target": target, "reference": {"entity_kind": "hardware", "entity_id": "hardware"}},
            {"op": "ADD_REFERENCE", "target": target, "reference": {"entity_kind": "hardware", "entity_id": "hardware"}},
        ])
        self.assertTrue(assess_fixture_plan(plan)["valid"])
        scalar = make_target(segments=[{"kind": "property", "name": "source_id"}])
        with self.assertRaises(ValueError):
            make_fixture_plan(operations=[
                {"op": "ADD_REFERENCE", "target": scalar, "reference": {"entity_kind": "hardware", "entity_id": "hardware"}},
                {"op": "ADD_REFERENCE", "target": scalar, "reference": {"entity_kind": "hardware", "entity_id": "hardware-2"}},
            ], entities=[fixture_context()[5], {**fixture_context()[5], "entity_id": "hardware-2"}])

    def test_unordered_literal_collection_is_local_and_multiplicity_preserved(self):
        target = make_target(segments=[{"kind": "property", "name": "custom_fields"}])
        semantics = [{"path": ["members"], "order": "unordered"}]
        first = make_fixture_plan(operations=[{"op": "SET_VALUE", "target": target, "value_source": literal({"members": ["alpha", "beta"], "sequence": ["one", "two"]}, collection_semantics=semantics)}])
        second = make_fixture_plan(operations=[{"op": "SET_VALUE", "target": target, "value_source": literal({"members": ["beta", "alpha"], "sequence": ["one", "two"]}, collection_semantics=semantics)}])
        self.assertEqual(first["plan_id"], second["plan_id"])
        third = make_fixture_plan(operations=[{"op": "SET_VALUE", "target": target, "value_source": literal({"members": ["alpha", "beta", "beta"], "sequence": ["one", "two"]}, collection_semantics=semantics)}])
        self.assertNotEqual(first["plan_id"], third["plan_id"])
        ordered = make_fixture_plan(operations=[{"op": "SET_VALUE", "target": target, "value_source": literal({"members": ["beta", "alpha"], "sequence": ["two", "one"]}, collection_semantics=semantics)}])
        self.assertNotEqual(first["plan_id"], ordered["plan_id"])


class GenerationPlanPolicyTests(unittest.TestCase):
    def issue_plan(self, code, *, fact_ids=(), mapping_ids=()):
        return make_fixture_plan(issues=[{
            "issue_id": f"issue-{code.lower()}",
            "code": code,
            "source": {"kind": "fixture", "id": "fixture-issue"},
            "fact_ids": list(fact_ids),
            "mapping_ids": list(mapping_ids),
            "reason": f"fixture {code}",
        }], operations=[] if fact_ids or mapping_ids else None)

    def test_issue_matrix(self):
        fact_id = fixture_context()[7]["fact_id"]
        expected = {
            "NOTES_ONLY": (True, True, False, False),
            "OMIT_UNKNOWN": (True, True, False, False),
            "CONFLICT": (True, True, True, True),
            "VOCAB_GAP": (True, False, False, True),
            "SCHEMA_GAP": (True, False, False, True),
            "VALIDATION_FAILED": (True, False, False, True),
            "IDENTITY_AMBIGUOUS": (True, False, False, True),
            "SOURCE_NOT_FOUND": (True, True, True, True),
            "INSUFFICIENT_EVIDENCE": (True, True, True, True),
        }
        for code, values in expected.items():
            plan = self.issue_plan(code, fact_ids=[fact_id] if code in {"CONFLICT", "SOURCE_NOT_FOUND", "INSUFFICIENT_EVIDENCE"} else ())
            result = assess_fixture_plan(plan)
            self.assertEqual((result["valid"], result["generation_allowed"], any(item["candidate_incomplete"] for item in result["issue_impacts"]), result["publication_blocking"]), values, code)

    def test_conflict_selection_is_rejected(self):
        context = fixture_context()
        fact_id = context[7]["fact_id"]
        mapping_id = context[8]["mapping_id"]
        with self.assertRaises(ValueError):
            make_fixture_plan(issues=[{
                "issue_id": "issue-conflict",
                "code": "CONFLICT",
                "source": {"kind": "fixture", "id": "fixture-issue"},
                "fact_ids": [fact_id],
                "mapping_ids": [mapping_id],
                "reason": "fixture conflict",
            }])

    def test_open_world_unknown_and_explicit_zero_are_distinct(self):
        unknown = self.issue_plan("OMIT_UNKNOWN", fact_ids=["unknown-fact"])
        zero = make_fixture_plan(operations=[{"op": "SET_VALUE", "target": make_target(segments=[{"kind": "property", "name": "custom_fields"}]), "value_source": literal(0)}])
        self.assertTrue(assess_fixture_plan(unknown)["generation_allowed"])
        self.assertEqual(zero["operations"][0]["value_source"]["value"], 0)


class GenerationPlanPersistenceTests(unittest.TestCase):
    def test_persistence_and_rerun_states(self):
        plan = make_fixture_plan()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = fixture_context()
            first = write_generation_plan(plan, root, extraction_result=context[0], mapping_result=context[1], vocabularies={"units": UNITS})
            second = write_generation_plan(copy.deepcopy(plan), root, extraction_result=context[0], mapping_result=context[1], vocabularies={"units": UNITS})
            self.assertEqual(first, second)
            self.assertEqual(compare_generation_plans(plan, copy.deepcopy(plan), extraction_result=context[0], mapping_result=context[1], vocabularies={"units": UNITS}), "NO_CHANGE")
            changed = copy.deepcopy(plan)
            changed["operations"][0]["value_source"] = literal("0.795")
            changed["plan_id"] = plan_id(changed)
            self.assertEqual(compare_generation_plans(plan, changed, extraction_result=context[0], mapping_result=context[1], vocabularies={"units": UNITS}), "CHANGED")
            stale = copy.deepcopy(plan)
            stale["input_bindings"]["mapping"]["semantic_hash"] = "sha256:changed"
            stale["plan_id"] = plan_id(stale)
            self.assertEqual(compare_generation_plans(plan, stale, extraction_result=context[0], mapping_result=context[1], vocabularies={"units": UNITS}), "STALE")
            self.assertEqual(read_generation_plan(first)["plan_id"], plan["plan_id"])

    def test_phase_one_does_not_create_candidates_or_equipment(self):
        self.assertFalse((Path.cwd() / ".ingestion/candidates").exists())
        self.assertFalse((Path.cwd() / "equipment/qsys/nvm-302e.json").exists())


if __name__ == "__main__":
    unittest.main()
