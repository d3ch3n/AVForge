import copy
import json
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/equipment.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def load_record(path):
    return json.loads((ROOT / path).read_text())


def with_coverage(record, coverage):
    value = copy.deepcopy(record)
    if coverage is None:
        value.pop("catalog_coverage", None)
    else:
        value["catalog_coverage"] = coverage
    return value


class EquipmentSchemaV34Tests(unittest.TestCase):
    def assert_valid(self, record):
        self.assertEqual(list(VALIDATOR.iter_errors(record)), [])

    def assert_invalid(self, record):
        self.assertTrue(list(VALIDATOR.iter_errors(record)))

    def test_cc01_coverage_absent(self):
        self.assert_valid(with_coverage(load_record("equipment/qsys/core-8-flex.json"), None))

    def test_cc02_empty_coverage_is_valid(self):
        self.assert_valid(with_coverage(load_record("equipment/qsys/core-8-flex.json"), {}))

    def test_cc03_complete_false(self):
        self.assert_valid(with_coverage(load_record("equipment/qsys/core-8-flex.json"), {"communication_protocols": {"complete": False}}))

    def test_cc04_complete_true(self):
        self.assert_valid(with_coverage(load_record("equipment/qsys/core-8-flex.json"), {"communication_protocols": {"complete": True}}))

    def test_cc05_complete_string_invalid(self):
        self.assert_invalid(with_coverage(load_record("equipment/qsys/core-8-flex.json"), {"communication_protocols": {"complete": "true"}}))

    def test_cc06_complete_required(self):
        self.assert_invalid(with_coverage(load_record("equipment/qsys/core-8-flex.json"), {"communication_protocols": {}}))

    def test_cc07_unknown_communication_protocol_field_invalid(self):
        self.assert_invalid(with_coverage(load_record("equipment/qsys/core-8-flex.json"), {"communication_protocols": {"complete": True, "notes": "x"}}))

    def test_cc08_unknown_coverage_field_invalid(self):
        self.assert_invalid(with_coverage(load_record("equipment/qsys/core-8-flex.json"), {"other": {}}))

    def test_cc09_approved_incomplete_valid(self):
        record = with_coverage(load_record("equipment/qsys/core-8-flex.json"), {"communication_protocols": {"complete": False}})
        record["status"] = "approved"
        self.assert_valid(record)

    def test_cc10_draft_complete_valid(self):
        record = with_coverage(load_record("equipment/qsys/core-8-flex.json"), {"communication_protocols": {"complete": True}})
        record["status"] = "draft"
        self.assert_valid(record)

    def test_cc11_chassis_complete_structurally_valid(self):
        self.assert_valid(with_coverage(load_record("equipment/crestron/dmf-ci-8.json"), {"communication_protocols": {"complete": True}}))

    def test_cc12_module_complete_valid(self):
        self.assert_valid(with_coverage(load_record("equipment/crestron/dm-nvx-360c.json"), {"communication_protocols": {"complete": True}}))

    def test_cc13_standalone_without_coverage_valid(self):
        self.assert_valid(load_record("equipment/qsys/core-8-flex.json"))

    def test_cc14_hybrid_with_coverage_valid(self):
        record = with_coverage(load_record("equipment/qsys/core-8-flex.json"), {"communication_protocols": {"complete": True}})
        record["modularity"] = {"role": "hybrid", "slots": [{"id": "slot", "label": "slot", "slot_type": "slot"}]}
        self.assert_valid(record)

    def test_cc15_complete_null_invalid(self):
        self.assert_invalid(with_coverage(load_record("equipment/qsys/core-8-flex.json"), {"communication_protocols": {"complete": None}}))

    def test_cc16_complete_integer_invalid(self):
        self.assert_invalid(with_coverage(load_record("equipment/qsys/core-8-flex.json"), {"communication_protocols": {"complete": 1}}))

    def test_cc17_coverage_array_invalid(self):
        self.assert_invalid(with_coverage(load_record("equipment/qsys/core-8-flex.json"), []))

    def test_cc18_communication_protocols_array_invalid(self):
        self.assert_invalid(with_coverage(load_record("equipment/qsys/core-8-flex.json"), {"communication_protocols": []}))

    def test_cc19_existing_capabilities_remain_valid(self):
        record = with_coverage(load_record("equipment/qsys/core-8-flex.json"), {"communication_protocols": {"complete": True}})
        self.assertTrue(record["communication_capabilities"])
        self.assert_valid(record)

    def test_cc20_three_current_records_without_coverage(self):
        for path in (
            "equipment/qsys/core-8-flex.json",
            "equipment/crestron/dmf-ci-8.json",
            "equipment/crestron/dm-nvx-360c.json",
        ):
            self.assert_valid(load_record(path))


if __name__ == "__main__":
    unittest.main()
