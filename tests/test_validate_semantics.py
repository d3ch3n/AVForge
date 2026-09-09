import json
import unittest
from pathlib import Path

from validator.validate_semantics import validate_records


ROOT = Path(__file__).resolve().parents[1]


def record(profile, profile_name="output"):
    return {
        "id": "test.electrical",
        "interfaces": [
            {
                "id": "audio-io",
                "electrical_characteristics": {profile_name: profile},
            }
        ],
    }


def errors_for(value):
    return validate_records([value])["issues"]


class ElectricalVariantSemanticTests(unittest.TestCase):
    def assert_valid(self, value):
        result = validate_records([value])
        self.assertEqual(result["summary"]["error_count"], 0, result["issues"])

    def assert_error(self, value, code):
        issues = errors_for(value)
        self.assertTrue(any(issue["code"] == code for issue in issues), issues)

    def test_s1_declared_balance_mode_is_valid(self):
        self.assert_valid(record({"balance_modes": ["balanced"], "variants": [{"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}]}))

    def test_s2_undeclared_balance_mode_is_invalid(self):
        self.assert_error(record({"balance_modes": ["balanced"], "variants": [{"conditions": {"balance_mode": "unbalanced"}, "maximum_level": {"value": 2, "unit": "volt-rms"}}]}), "ELECTRICAL_VARIANT_MODE_UNDECLARED")

    def test_s3_variants_without_balance_modes_are_invalid(self):
        self.assert_error(record({"variants": [{"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}]}), "ELECTRICAL_VARIANT_MODE_DOMAIN_MISSING")

    def test_s4_single_balanced_variant_is_valid(self):
        self.assert_valid(record({"balance_modes": ["balanced"], "variants": [{"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}]}))

    def test_s5_duplicate_balanced_variants_are_invalid(self):
        self.assert_error(record({"balance_modes": ["balanced"], "variants": [{"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}, {"conditions": {"balance_mode": "balanced"}, "impedance": {"nominal": {"value": 100, "unit": "ohm"}}}]}), "DUPLICATE_ELECTRICAL_VARIANT_MODE")

    def test_s6_duplicate_unbalanced_variants_are_invalid(self):
        self.assert_error(record({"balance_modes": ["unbalanced"], "variants": [{"conditions": {"balance_mode": "unbalanced"}, "maximum_level": {"value": 2, "unit": "volt-rms"}}, {"conditions": {"balance_mode": "unbalanced"}, "impedance": {"nominal": {"value": 100, "unit": "ohm"}}}]}), "DUPLICATE_ELECTRICAL_VARIANT_MODE")

    def test_s7_balanced_and_unbalanced_variants_are_valid(self):
        self.assert_valid(record({"balance_modes": ["balanced", "unbalanced"], "variants": [{"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}, {"conditions": {"balance_mode": "unbalanced"}, "maximum_level": {"value": 2, "unit": "volt-rms"}}]}))

    def test_s8_base_maximum_and_conditional_maximum_are_invalid(self):
        self.assert_error(record({"balance_modes": ["balanced"], "maximum_level": {"value": 4, "unit": "volt-rms"}, "variants": [{"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 2, "unit": "volt-rms"}}]}), "BASE_AND_CONDITIONAL_ELECTRICAL_PROPERTY")

    def test_s9_base_nominal_and_conditional_maximum_are_valid(self):
        self.assert_valid(record({"balance_modes": ["balanced"], "impedance": {"nominal": {"value": 100, "unit": "ohm"}}, "variants": [{"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}]}))

    def test_s10_base_nominal_and_conditional_nominal_are_invalid(self):
        self.assert_error(record({"balance_modes": ["balanced"], "impedance": {"nominal": {"value": 100, "unit": "ohm"}}, "variants": [{"conditions": {"balance_mode": "balanced"}, "impedance": {"nominal": {"value": 200, "unit": "ohm"}}}]}), "BASE_AND_CONDITIONAL_ELECTRICAL_PROPERTY")

    def test_s11_base_upper_bound_and_conditional_upper_bound_are_invalid(self):
        self.assert_error(record({"balance_modes": ["balanced"], "impedance": {"upper_bound": {"value": 100, "unit": "ohm", "inclusive": False}}, "variants": [{"conditions": {"balance_mode": "balanced"}, "impedance": {"upper_bound": {"value": 80, "unit": "ohm", "inclusive": False}}}]}), "BASE_AND_CONDITIONAL_ELECTRICAL_PROPERTY")

    def test_s12_base_nominal_and_conditional_upper_bound_are_valid(self):
        self.assert_valid(record({"balance_modes": ["balanced"], "impedance": {"nominal": {"value": 80, "unit": "ohm"}}, "variants": [{"conditions": {"balance_mode": "balanced"}, "impedance": {"upper_bound": {"value": 100, "unit": "ohm", "inclusive": False}}}]}))

    def test_s13_partial_variant_coverage_is_valid(self):
        self.assert_valid(record({"balance_modes": ["balanced", "unbalanced"], "variants": [{"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}]}))

    def test_s14_profile_without_variants_is_valid(self):
        self.assert_valid(record({"balance_modes": ["balanced"]}))

    def test_s15_existing_schema_35_shaped_electrical_profile_is_valid(self):
        self.assert_valid(json.loads((ROOT / "equipment/crestron/dm-nvx-360c.json").read_text()))

    def test_s16_core_8_flex_is_valid(self):
        self.assert_valid(json.loads((ROOT / "equipment/qsys/core-8-flex.json").read_text()))

    def test_s17_conceptual_dm_nvx_future_shape_is_valid(self):
        self.assert_valid(record({"balance_modes": ["balanced", "unbalanced"], "variants": [{"conditions": {"balance_mode": "balanced"}, "impedance": {"nominal": {"value": 200, "unit": "ohm"}}, "maximum_level": {"value": 4, "unit": "volt-rms"}}, {"conditions": {"balance_mode": "unbalanced"}, "impedance": {"nominal": {"value": 100, "unit": "ohm"}}, "maximum_level": {"value": 2, "unit": "volt-rms"}}]}))

    def test_s18_conceptual_hd_md_future_shape_is_valid(self):
        self.assert_valid(record({"balance_modes": ["balanced", "unbalanced"], "impedance": {"upper_bound": {"value": 100, "unit": "ohm", "inclusive": False}}, "variants": [{"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}, {"conditions": {"balance_mode": "unbalanced"}, "maximum_level": {"value": 2, "unit": "volt-rms"}}]}))

    def test_s19_input_error_identifies_input_profile(self):
        issues = errors_for(record({"balance_modes": ["balanced"], "variants": [{"conditions": {"balance_mode": "unbalanced"}, "maximum_level": {"value": 2, "unit": "volt-rms"}}]}, "input"))
        issue = next(issue for issue in issues if issue["code"] == "ELECTRICAL_VARIANT_MODE_UNDECLARED")
        self.assertEqual(issue["profile"], "input")
        self.assertIn("electrical_characteristics.input", issue["json_path"])

    def test_s20_output_error_identifies_output_profile(self):
        issues = errors_for(record({"balance_modes": ["balanced"], "variants": [{"conditions": {"balance_mode": "unbalanced"}, "maximum_level": {"value": 2, "unit": "volt-rms"}}]}, "output"))
        issue = next(issue for issue in issues if issue["code"] == "ELECTRICAL_VARIANT_MODE_UNDECLARED")
        self.assertEqual(issue["profile"], "output")
        self.assertIn("electrical_characteristics.output", issue["json_path"])


if __name__ == "__main__":
    unittest.main()
