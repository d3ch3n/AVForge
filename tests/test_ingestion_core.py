import copy
import json
import tempfile
import unittest
from pathlib import Path

from ingestion.intake import IntakeError, parse_csv, parse_json
from ingestion.models import validate_evidence, validate_fact, validate_issue, validate_job, validate_mapping, validate_source
from ingestion.runner import publication_allowed, run_batch
from ingestion.state import aggregate_state, batch_summary, compare_jobs, new_job


def item(model="Model X", manufacturer="Vendor"):
    return {"manufacturer": manufacturer, "model": model}


def source(source_id="src-1", source_type="pdf", **extra):
    value = {"source_id": source_id, "source_type": source_type, "canonicality": "official-canonical", "tier": 1, "url": "https://example.test/source", "metadata": {"title": "Specifications"}}
    value.update(extra)
    return value


def evidence(evidence_id="ev-1", source_id="src-1", kind="pdf"):
    return {"evidence_id": evidence_id, "source_id": source_id, "locator": {"kind": kind, "page": 2} if kind == "pdf" else {"kind": kind, "heading": "Audio", "fragment": "#audio"}, "evidence_role": "primary"}


def fact(evidence_refs=None, precision="exact", polarity="POSITIVE_EXPLICIT", value=800):
    result = {"fact_id": "fact-1", "subject": {"kind": "interface", "local_id": "output-1"}, "property": "maximum_power", "qualifiers": {}, "conditions": [], "semantic_precision": precision, "polarity": polarity, "evidence_refs": evidence_refs or ["ev-1"], "extraction_method": "fixture", "evidence_status": "SUPPORTED"}
    if precision not in {"unknown", "not-rated"} and polarity not in {"UNKNOWN", "NOT_APPLICABLE"}:
        result["value"] = value
        result["unit"] = "watt"
    return result


class IntakeTests(unittest.TestCase):
    def test_json_intake_normalizes_and_preserves_original(self):
        items = parse_json({"contract_version": "1.0", "items": [{"manufacturer": " Vendor ", "model": " Model   X ", "notes": "  hint  "}]})
        self.assertEqual(items[0]["manufacturer"], "Vendor")
        self.assertEqual(items[0]["model"], "Model X")
        self.assertEqual(items[0]["original"]["model"], " Model   X ")

    def test_csv_intake_and_unknown_manufacturer(self):
        items = parse_csv("manufacturer,model\n,Model X\n")
        self.assertIsNone(items[0]["manufacturer"])
        self.assertEqual(items[0]["model"], "Model X")

    def test_malformed_intake_and_duplicate(self):
        with self.assertRaises(IntakeError) as invalid:
            parse_json({"items": []})
        self.assertEqual(invalid.exception.code, "INVALID_INTAKE")
        with self.assertRaises(IntakeError) as duplicate:
            parse_json({"contract_version": "1.0", "items": [item(), item()]})
        self.assertEqual(duplicate.exception.code, "DUPLICATE_ITEM")

    def test_equipment_alias_is_accepted_without_identity_resolution(self):
        parsed = parse_csv("equipment\nVendor Model X\n")
        self.assertIsNone(parsed[0]["manufacturer"])
        self.assertEqual(parsed[0]["model"], "Vendor Model X")

    def test_optional_hints_are_normalized(self):
        parsed = parse_json({"contract_version": "1.0", "items": [{"model": "X", "local_sources": [" manual.pdf "], "official_url": " https://example.test/x "}]})
        self.assertEqual(parsed[0]["local_sources"], ["manual.pdf"])
        self.assertEqual(parsed[0]["official_url"], "https://example.test/x")

    def test_unsupported_field_is_rejected(self):
        with self.assertRaises(IntakeError):
            parse_json({"contract_version": "1.0", "items": [{"model": "X", "technical_specs": {}}]})

    def test_job_id_is_deterministic_and_position_independent(self):
        value = {"contract_version": "1.0", "items": [item()]}
        first = parse_json(value)[0]["job_id"]
        second = parse_json(value)[0]["job_id"]
        self.assertEqual(first, second)
        moved = parse_json({"contract_version": "1.0", "items": [item("Other"), item()]})[1]["job_id"]
        self.assertEqual(first, moved)

    def test_duplicate_is_rejected_within_batch_but_stable_across_batches(self):
        with self.assertRaises(IntakeError) as duplicate:
            parse_csv("manufacturer,model\nVendor,Model X\nVendor,Model X\n")
        self.assertEqual(duplicate.exception.code, "DUPLICATE_ITEM")
        first = parse_json({"contract_version": "1.0", "items": [item()]})[0]["job_id"]
        second = parse_json({"contract_version": "1.0", "items": [{"model": "Other"}, item()]})[1]["job_id"]
        self.assertEqual(first, second)


class ModelTests(unittest.TestCase):
    def test_measurement_precisions_and_polarities(self):
        for precision in ("exact", "minimum", "maximum", "range", "approximate", "nominal"):
            value = fact(precision=precision)
            if precision == "range":
                value["value"] = {"minimum": 100, "maximum": 240}
            from ingestion.models import validate_fact
            validate_fact(value)
        validate_fact(fact(precision="unknown", polarity="UNKNOWN"))
        validate_fact(fact(precision="not-rated", polarity="NEGATIVE_EXPLICIT"))

    def test_malformed_fact_is_rejected(self):
        value = fact()
        value["polarity"] = "UNKNOWN"
        value["evidence_refs"] = []
        with self.assertRaises(ValueError):
            from ingestion.models import validate_fact
            validate_fact(value)

    def test_source_and_locators(self):
        validate_source(source())
        validate_source(source("src-html", "html"))
        validate_evidence(evidence())
        validate_evidence(evidence("ev-html", "src-1", "html"))

    def test_multiple_evidence_references(self):
        value = fact(evidence_refs=["ev-1", "ev-2"])
        validate_fact(value)

    def test_mapping_states_are_closed(self):
        for disposition in ("STRUCTURED", "NOTES_ONLY", "OMIT_UNKNOWN", "VOCAB_GAP", "SCHEMA_GAP", "CONFLICT"):
            validate_mapping({"fact_id": "fact-1", "disposition": disposition})
        with self.assertRaises(ValueError):
            validate_mapping({"fact_id": "fact-1", "disposition": "STRUCTURED_TO_NOTES"})

    def test_issue_has_machine_readable_references(self):
        validate_issue({"issue_id": "i-1", "code": "SOURCE_CONFLICT", "severity": "ERROR", "stage": "conflict_detection", "message": "conflict", "blocking": True, "subjects": ["fact-1"], "evidence_refs": ["ev-1"]})

    def test_job_serializes_and_references_are_checked(self):
        job = new_job(parse_json({"contract_version": "1.0", "items": [item()]})[0])
        job["sources"] = [source()]
        job["evidence"] = [evidence()]
        job["facts"] = [fact()]
        job["mappings"] = [{"fact_id": "fact-1", "disposition": "STRUCTURED"}]
        validate_job(job)
        broken = copy.deepcopy(job)
        broken["facts"][0]["evidence_refs"] = ["missing"]
        with self.assertRaises(ValueError):
            validate_job(broken)

    def test_source_requires_reference(self):
        with self.assertRaises(ValueError):
            validate_source({"source_id": "src", "source_type": "pdf", "canonicality": "official", "tier": 1})

    def test_fact_numeric_value_requires_unit(self):
        value = fact()
        value.pop("unit")
        with self.assertRaises(ValueError):
            validate_fact(value)

    def test_bounds_and_ranges_require_valid_shapes(self):
        minimum = fact(precision="minimum")
        minimum.pop("value")
        minimum.pop("unit")
        with self.assertRaises(ValueError):
            validate_fact(minimum)
        invalid_range = fact(precision="range")
        invalid_range["value"] = {"minimum": 10, "maximum": 1}
        with self.assertRaises(ValueError):
            validate_fact(invalid_range)

    def test_absent_precision_rejects_value_and_unit(self):
        unknown = fact(precision="unknown", polarity="UNKNOWN")
        unknown["value"] = 0
        unknown["unit"] = "watt"
        with self.assertRaises(ValueError):
            validate_fact(unknown)

    def test_duplicate_sources_evidence_and_mappings_are_rejected(self):
        job = new_job(parse_json({"contract_version": "1.0", "items": [item()]})[0])
        job["sources"] = [source(), source()]
        with self.assertRaises(ValueError):
            validate_job(job)
        job["sources"] = [source()]
        job["evidence"] = [evidence(), evidence()]
        with self.assertRaises(ValueError):
            validate_job(job)
        job["evidence"] = [evidence()]
        job["facts"] = [fact()]
        job["mappings"] = [{"fact_id": "fact-1", "disposition": "STRUCTURED"}, {"fact_id": "fact-1", "disposition": "CONFLICT"}]
        with self.assertRaises(ValueError):
            validate_job(job)

    def test_job_accepts_all_stage_statuses(self):
        job = new_job(parse_json({"contract_version": "1.0", "items": [item()]})[0])
        for status in ("PENDING", "RUNNING", "COMPLETED", "BLOCKED", "FAILED", "SKIPPED"):
            candidate = copy.deepcopy(job)
            candidate["stages"]["identity_resolution"] = status
            validate_job(candidate)


class StateTests(unittest.TestCase):
    def complete_job(self):
        job = new_job(parse_json({"contract_version": "1.0", "items": [item()]})[0])
        job["issues"] = []
        job["resolved_identity"] = {"manufacturer": "Vendor", "canonical_model": "Model X", "identity_status": "RESOLVED"}
        job["pipeline_status"] = "COMPLETED"
        job["sources"] = [source()]
        job["evidence"] = [evidence()]
        job["facts"] = [fact()]
        job["mappings"] = [{"fact_id": "fact-1", "disposition": "STRUCTURED"}]
        for stage in job["stages"]:
            if stage not in {"publication"}:
                job["stages"][stage] = "COMPLETED"
        job["stages"]["publication"] = "SKIPPED"
        job["validations"] = [{"stage": stage, "passed": True} for stage in ("json_parse", "equipment_schema", "semantic_validation", "existing_tests", "compatibility_tests", "catalog_validation", "git_diff_check", "machine_audit")]
        return job

    def test_ready_and_validation_precedence(self):
        job = self.complete_job()
        self.assertEqual(aggregate_state(job), "READY")
        job["issues"] = [{"code": "SCHEMA_GAP"}]
        self.assertEqual(aggregate_state(job), "SCHEMA_GAP")
        job["issues"].append({"code": "VALIDATION_FAILED"})
        self.assertEqual(aggregate_state(job), "VALIDATION_FAILED")

    def test_failed_validation_result_has_highest_precedence(self):
        job = self.complete_job()
        job["validations"] = [{"stage": "semantic_validation", "passed": False}]
        self.assertEqual(aggregate_state(job), "VALIDATION_FAILED")

    def test_all_gap_and_review_precedence(self):
        job = self.complete_job()
        job["issues"] = [{"code": "REVIEW_REQUIRED"}, {"code": "VOCAB_GAP"}, {"code": "IDENTITY_AMBIGUOUS"}]
        self.assertEqual(aggregate_state(job), "VOCAB_GAP")
        job["issues"].append({"code": "SOURCE_NOT_FOUND"})
        self.assertEqual(aggregate_state(job), "VOCAB_GAP")

    def test_blocked_future_stage_is_not_validation_failure(self):
        job = new_job(parse_json({"contract_version": "1.0", "items": [item()]})[0])
        self.assertEqual(job["stages"]["identity_resolution"], "BLOCKED")
        self.assertEqual(aggregate_state(job), "NEEDS_REVIEW")

    def test_mapping_gaps_and_summary(self):
        job = self.complete_job()
        job["issues"] = []
        job["mappings"] = [{"fact_id": "fact-1", "disposition": "SCHEMA_GAP"}]
        self.assertEqual(aggregate_state(job), "SCHEMA_GAP")
        self.assertEqual(batch_summary([job])["states"]["SCHEMA_GAP"], 1)

    def test_source_and_evidence_issues_aggregate(self):
        job = self.complete_job()
        job["issues"] = [{"code": "SOURCE_NOT_FOUND"}]
        self.assertEqual(aggregate_state(job), "SOURCE_NOT_FOUND")
        job["issues"] = [{"code": "INSUFFICIENT_EVIDENCE"}]
        self.assertEqual(aggregate_state(job), "INSUFFICIENT_EVIDENCE")

    def test_review_issue_aggregates_without_validation_failure(self):
        job = self.complete_job()
        job["issues"] = [{"code": "REVIEW_REQUIRED"}]
        self.assertEqual(aggregate_state(job), "NEEDS_REVIEW")

    def test_ready_requires_validation_results(self):
        job = self.complete_job()
        job["validations"] = []
        self.assertEqual(aggregate_state(job), "NEEDS_REVIEW")

    def test_blocked_pipeline_cannot_be_ready(self):
        job = self.complete_job()
        job["pipeline_status"] = "BLOCKED"
        self.assertEqual(aggregate_state(job), "NEEDS_REVIEW")


class RerunTests(unittest.TestCase):
    def test_rerun_categories(self):
        base = {"intake": {"model": "X"}, "resolved_identity": {"model": "X"}, "mappings": [], "candidate": None, "facts": [], "sources": [{"source_id": "s", "content_hash": "sha256:a", "retrieved_at": "one"}]}
        self.assertEqual(compare_jobs(base, copy.deepcopy(base)), "NO_CHANGE")
        timestamp = copy.deepcopy(base)
        timestamp["sources"][0]["retrieved_at"] = "two"
        self.assertEqual(compare_jobs(base, timestamp), "NO_CHANGE")
        source_changed = copy.deepcopy(base)
        source_changed["sources"][0]["content_hash"] = "sha256:b"
        self.assertEqual(compare_jobs(base, source_changed), "SOURCE_UPDATED")
        facts_changed = copy.deepcopy(base)
        facts_changed["facts"] = [fact()]
        self.assertEqual(compare_jobs(base, facts_changed), "FACTS_CHANGED")
        identity_changed = copy.deepcopy(base)
        identity_changed["resolved_identity"]["model"] = "Y"
        self.assertEqual(compare_jobs(base, identity_changed), "REVIEW_REQUIRED")

    def test_reordered_collections_do_not_change_rerun_result(self):
        base = {"intake": {}, "resolved_identity": {}, "mappings": [{"fact_id": "b", "disposition": "STRUCTURED"}, {"fact_id": "a", "disposition": "NOTES_ONLY"}], "candidate": None, "facts": [], "sources": [{"source_id": "b", "content_hash": "b"}, {"source_id": "a", "content_hash": "a"}]}
        reordered = copy.deepcopy(base)
        reordered["mappings"].reverse()
        reordered["sources"].reverse()
        self.assertEqual(compare_jobs(base, reordered), "NO_CHANGE")

    def test_mapping_change_requires_review(self):
        base = {"intake": {}, "resolved_identity": {}, "mappings": [], "candidate": None, "facts": [], "sources": []}
        changed = copy.deepcopy(base)
        changed["mappings"] = [{"fact_id": "f", "disposition": "NOTES_ONLY"}]
        self.assertEqual(compare_jobs(base, changed), "REVIEW_REQUIRED")


class BatchTests(unittest.TestCase):
    def test_independent_batch_jobs_and_runtime_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            intake = root / "list.json"
            intake.write_text(json.dumps({"contract_version": "1.0", "items": [item("One"), item("Two", None)]}))
            result = run_batch(intake, "json", root)
            self.assertEqual(result["summary"]["total"], 2)
            self.assertEqual(len(list((root / ".ingestion/jobs").glob("*.json"))), 2)
            self.assertTrue(all(job["primary_state"] == "NEEDS_REVIEW" for job in result["jobs"]))

    def test_publication_is_only_eligibility(self):
        job = StateTests().complete_job()
        self.assertTrue(publication_allowed(job))
        self.assertFalse((Path.cwd() / "equipment/qsys/nvm-302e.json").exists())

    def test_runtime_paths_are_ignored(self):
        import subprocess
        result = subprocess.run(["git", "check-ignore", ".ingestion/jobs/example.json", "ingestion/__pycache__/example.pyc"], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
