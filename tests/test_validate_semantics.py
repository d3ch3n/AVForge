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


def output_interface(interface_id, direction="output", signal_type="audio"):
    interface = {"id": interface_id, "direction": direction}
    if signal_type is not None:
        interface["signals"] = [{"id": f"{interface_id}-signal", "signal_type": signal_type}]
    return interface


def amplifier_point(point_id="op-1", load=None, ratings=None):
    return {
        "id": point_id,
        "load": load if load is not None else {"type": "low_impedance", "impedance": {"value": 8, "unit": "ohm"}},
        "ratings": ratings if ratings is not None else [{"type": "maximum", "power": {"value": 1000, "unit": "watt"}}],
    }


def amplifier_entry(entry_id="amp-1", topology="independent", groups=None, points=None):
    return {
        "id": entry_id,
        "topology": topology,
        "member_groups": groups if groups is not None else [["output-a"]],
        "operating_points": points if points is not None else [amplifier_point()],
    }


def amplifier_value(interfaces, capabilities):
    return {
        "id": "test.amplifier",
        "interfaces": interfaces,
        "amplifier_output_capabilities": capabilities,
    }


def two_output_interfaces():
    return [output_interface("output-a"), output_interface("output-b")]


class AmplifierCapabilitySemanticTests(unittest.TestCase):
    def assert_valid(self, value):
        result = validate_records([value])
        self.assertEqual(result["summary"]["error_count"], 0, result["issues"])

    def assert_error(self, value, code):
        issues = errors_for(value)
        self.assertTrue(any(issue["code"] == code and issue["severity"] == "ERROR" for issue in issues), issues)

    def assert_warning(self, value, code):
        result = validate_records([value])
        self.assertEqual(result["summary"]["error_count"], 0, result["issues"])
        self.assertTrue(any(issue["code"] == code and issue["severity"] == "WARNING" for issue in result["issues"]), result["issues"])

    def test_m01_valid_independent(self):
        self.assert_valid(amplifier_value(two_output_interfaces(), [amplifier_entry()]))

    def test_m02_valid_bridge(self):
        self.assert_valid(amplifier_value(
            two_output_interfaces(),
            [amplifier_entry("amp-bridge", "bridge", [["output-a", "output-b"]],
                             [amplifier_point("op-140v", {"type": "constant_voltage", "voltage": {"value": 140, "unit": "volt"}})])],
        ))

    def test_m03_valid_parallel_with_three_members(self):
        self.assert_valid(amplifier_value(
            [output_interface("output-a"), output_interface("output-b"), output_interface("output-c")],
            [amplifier_entry("amp-parallel", "parallel", [["output-a", "output-b", "output-c"]])],
        ))

    def test_m04_valid_bridge_parallel(self):
        self.assert_valid(amplifier_value(
            [output_interface("output-a"), output_interface("output-b"), output_interface("output-c"), output_interface("output-d")],
            [amplifier_entry("amp-bp", "bridge_parallel", [["output-a", "output-b", "output-c", "output-d"]])],
        ))

    def test_m05_unresolved_member_is_error(self):
        self.assert_error(
            amplifier_value(two_output_interfaces(), [amplifier_entry(groups=[["output-a", "output-missing"]])]),
            "INVALID_INTERNAL_REFERENCE",
        )

    def test_m06_input_only_member_is_error(self):
        self.assert_error(
            amplifier_value(
                [output_interface("output-a"), output_interface("input-a", direction="input")],
                [amplifier_entry("amp-bridge", "bridge", [["output-a", "input-a"]])],
            ),
            "AMPLIFIER_MEMBER_NOT_OUTPUT",
        )

    def test_m07_independent_with_two_members_is_error(self):
        self.assert_error(
            amplifier_value(two_output_interfaces(), [amplifier_entry(groups=[["output-a", "output-b"]])]),
            "AMPLIFIER_ARITY_INDEPENDENT",
        )

    def test_m08_bridge_with_one_member_is_error(self):
        self.assert_error(
            amplifier_value(two_output_interfaces(), [amplifier_entry("amp-bridge", "bridge", [["output-a"]])]),
            "AMPLIFIER_ARITY_COMBINED",
        )

    def test_m09_parallel_with_one_member_is_error(self):
        self.assert_error(
            amplifier_value(two_output_interfaces(), [amplifier_entry("amp-parallel", "parallel", [["output-a"]])]),
            "AMPLIFIER_ARITY_COMBINED",
        )

    def test_m10_bridge_parallel_with_one_member_is_error(self):
        self.assert_error(
            amplifier_value(two_output_interfaces(), [amplifier_entry("amp-bp", "bridge_parallel", [["output-a"]])]),
            "AMPLIFIER_ARITY_COMBINED",
        )

    def test_m11_low_impedance_wrong_unit_is_error(self):
        self.assert_error(
            amplifier_value(two_output_interfaces(), [amplifier_entry(points=[amplifier_point(
                load={"type": "low_impedance", "impedance": {"value": 8, "unit": "volt"}})])]),
            "AMPLIFIER_LOAD_UNIT_INVALID",
        )

    def test_m12_constant_voltage_wrong_unit_is_error(self):
        self.assert_error(
            amplifier_value(two_output_interfaces(), [amplifier_entry(points=[amplifier_point(
                load={"type": "constant_voltage", "voltage": {"value": 70, "unit": "ohm"}})])]),
            "AMPLIFIER_LOAD_UNIT_INVALID",
        )

    def test_m13_power_wrong_unit_is_error(self):
        self.assert_error(
            amplifier_value(two_output_interfaces(), [amplifier_entry(points=[amplifier_point(
                ratings=[{"type": "maximum", "power": {"value": 1000, "unit": "volt"}}])])]),
            "AMPLIFIER_POWER_UNIT_INVALID",
        )

    def test_m14_unknown_rating_type_is_warning(self):
        self.assert_warning(
            amplifier_value(two_output_interfaces(), [amplifier_entry(points=[amplifier_point(
                ratings=[{"type": "peak", "power": {"value": 1200, "unit": "watt"}}])])]),
            "AMPLIFIER_RATING_TYPE_UNKNOWN",
        )

    def test_m15_member_without_audio_signal_is_warning(self):
        self.assert_warning(
            amplifier_value(
                [output_interface("output-a"), {"id": "lan-a", "direction": "bidirectional",
                                                "signals": [{"id": "lan-a-ethernet", "signal_type": "network"}]}],
                [amplifier_entry("amp-bridge", "bridge", [["output-a", "lan-a"]])],
            ),
            "AMPLIFIER_MEMBER_SIGNAL_UNDECLARED",
        )

    def test_m16_member_without_signals_is_warning(self):
        self.assert_warning(
            amplifier_value(
                [output_interface("output-a"), output_interface("output-b", signal_type=None)],
                [amplifier_entry("amp-bridge", "bridge", [["output-a", "output-b"]])],
            ),
            "AMPLIFIER_MEMBER_SIGNAL_UNDECLARED",
        )

    def test_m17_duplicate_capability_id_is_error(self):
        self.assert_error(
            amplifier_value(two_output_interfaces(), [amplifier_entry("amp-dup"), amplifier_entry("amp-dup", "bridge", [["output-a", "output-b"]])]),
            "DUPLICATE_AMPLIFIER_CAPABILITY_ID",
        )

    def test_m18_duplicate_operating_point_id_within_capability_is_error(self):
        self.assert_error(
            amplifier_value(two_output_interfaces(), [amplifier_entry(points=[amplifier_point("op-dup"), amplifier_point("op-dup")])]),
            "DUPLICATE_AMPLIFIER_OPERATING_POINT_ID",
        )

    def test_m19_same_operating_point_id_across_capabilities_is_valid(self):
        self.assert_valid(amplifier_value(
            two_output_interfaces(),
            [amplifier_entry("amp-one"), amplifier_entry("amp-two", "bridge", [["output-a", "output-b"]])],
        ))

    def test_m20_bidirectional_member_is_valid(self):
        self.assert_valid(amplifier_value(
            [output_interface("output-a", direction="bidirectional"), output_interface("output-b", direction="bidirectional")],
            [amplifier_entry("amp-bridge", "bridge", [["output-a", "output-b"]])],
        ))


if __name__ == "__main__":
    unittest.main()
