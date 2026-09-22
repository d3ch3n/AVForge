import json
import copy
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


def application_record(applications):
    return {"id": "test.applications", "applications": applications}


class ApplicationModelSemanticTests(unittest.TestCase):
    def assert_valid(self, value):
        result = validate_records([value])
        self.assertEqual(result["summary"]["error_count"], 0, result["issues"])

    def assert_error(self, value, code):
        issues = errors_for(value)
        self.assertTrue(any(issue["code"] == code and issue["severity"] == "ERROR" for issue in issues), issues)

    def test_duplicate_application_ids_are_rejected(self):
        self.assert_error(application_record([{"id": "app", "name": "One"}, {"id": "app", "name": "Two"}]), "DUPLICATE_APPLICATION_ID")

    def test_duplicate_application_names_are_allowed(self):
        self.assert_valid(application_record([{"id": "app-a", "name": "Same"}, {"id": "app-b", "name": "Same"}]))

    def test_application_condition_reference_uses_id(self):
        self.assert_valid(application_record([{"id": "app-a", "name": "Same"}, {"id": "app-b", "name": "Other", "state_assertions": [{"state": "available", "value": True, "conditions": [{"kind": "application", "value": "app-a"}]}]}]))
        self.assert_error(application_record([{"id": "app-a", "name": "Same"}, {"id": "app-b", "name": "Other", "state_assertions": [{"state": "available", "value": True, "conditions": [{"kind": "application", "value": "missing"}]}]}]), "INVALID_APPLICATION_REFERENCE")
        self.assert_error(application_record([{"id": "app-a", "name": "Same", "state_assertions": [{"state": "available", "value": True, "conditions": [{"kind": "application", "value": "Same"}]}]}]), "INVALID_APPLICATION_REFERENCE")

    def test_duplicate_conditions_are_rejected(self):
        self.assert_error(application_record([{"id": "app", "name": "App", "state_assertions": [{"state": "available", "value": True, "conditions": [{"kind": "license", "value": "A"}, {"kind": "license", "value": "A"}]}]}]), "DUPLICATE_APPLICATION_CONDITION")

    def test_empty_conditions_are_rejected(self):
        self.assert_error(application_record([{"id": "app", "name": "App", "state_assertions": [{"state": "available", "value": True, "conditions": []}]}]), "EMPTY_APPLICATION_CONDITIONS")

    def test_assertion_duplicates_and_reversed_condition_order_are_rejected(self):
        first = {"state": "available", "value": True, "conditions": [{"kind": "license", "value": "A"}, {"kind": "configuration", "value": "B"}]}
        reversed_order = {"state": "available", "value": True, "conditions": list(reversed(first["conditions"]))}
        self.assert_error(application_record([{"id": "app", "name": "App", "state_assertions": [first, reversed_order]}]), "DUPLICATE_APPLICATION_ASSERTION")

    def test_assertion_contradictions_and_reversed_condition_order_are_rejected(self):
        first = {"state": "available", "value": True, "conditions": [{"kind": "license", "value": "A"}, {"kind": "configuration", "value": "B"}]}
        reversed_order = {"state": "available", "value": False, "conditions": list(reversed(first["conditions"]))}
        self.assert_error(application_record([{"id": "app", "name": "App", "state_assertions": [first, reversed_order]}]), "CONTRADICTORY_APPLICATION_ASSERTION")

    def test_same_state_under_different_conditions_is_valid(self):
        self.assert_valid(application_record([{"id": "app", "name": "App", "state_assertions": [
            {"state": "available", "value": True, "conditions": [{"kind": "license", "value": "A"}]},
            {"state": "available", "value": True, "conditions": [{"kind": "license", "value": "B"}]},
        ]}]))

    def test_states_are_orthogonal_and_absence_is_not_negative(self):
        self.assert_valid(application_record([{"id": "app", "name": "App", "state_assertions": [{"state": "available", "value": True}]}]))
        self.assert_valid(application_record([{"id": "app", "name": "App", "state_assertions": [{"state": "installed", "value": True}, {"state": "available", "value": False}]}]))
        self.assert_valid(application_record([{"id": "app", "name": "App", "state_assertions": [{"state": "available", "value": True}, {"state": "installed", "value": False}]}]))

    def test_malicious_condition_values_are_inert_data(self):
        self.assert_valid(application_record([{"id": "app", "name": "App", "state_assertions": [{"state": "available", "value": True, "conditions": [{"kind": "license", "value": "__import__('os').system('x')"}, {"kind": "configuration", "value": "$(rm -rf /)"}, {"kind": "firmware", "value": "<script>alert(1)</script>"}]}]}]))


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


def operating_case_record():
    return json.loads((ROOT / "tests/fixtures/electrical-operating-case-nvm.json").read_text())


class ElectricalOperatingCaseSemanticTests(unittest.TestCase):
    def assert_valid(self, value):
        result = validate_records([value])
        self.assertEqual(result["summary"]["error_count"], 0, result["issues"])

    def assert_error(self, value, code):
        issues = errors_for(value)
        self.assertTrue(any(issue["code"] == code and issue["severity"] == "ERROR" for issue in issues), issues)

    def test_nvm_fixture_is_valid(self):
        self.assert_valid(operating_case_record())

    def test_source_and_mode_references_are_validated(self):
        value = operating_case_record()
        value["power"]["operating_cases"][0]["upstream"]["source_id"] = "missing"
        self.assert_error(value, "INVALID_POWER_OPERATING_SOURCE_REFERENCE")

        value = operating_case_record()
        value["power"]["operating_cases"][0]["upstream"]["mode_id"] = "missing"
        self.assert_error(value, "INVALID_POWER_OPERATING_MODE_REFERENCE")

        value = operating_case_record()
        value["power"]["sources"].append({"id": "other-source", "method": "PoE", "modes": [{"id": "other-mode", "poe": {"standard": "802.3at", "type": "2", "class": "4"}}]})
        value["power"]["operating_cases"][0]["upstream"]["mode_id"] = "other-mode"
        self.assert_error(value, "INVALID_POWER_OPERATING_MODE_REFERENCE")

    def test_duplicate_source_modes_and_case_ids_are_rejected(self):
        value = operating_case_record()
        value["power"]["sources"][0]["modes"].append(copy.deepcopy(value["power"]["sources"][0]["modes"][0]))
        self.assert_error(value, "DUPLICATE_POWER_SOURCE_MODE_ID")

        value = operating_case_record()
        value["power"]["operating_cases"][1]["id"] = value["power"]["operating_cases"][0]["id"]
        self.assert_error(value, "DUPLICATE_ELECTRICAL_OPERATING_CASE_ID")

    def test_interface_members_and_named_members_are_validated(self):
        value = operating_case_record()
        scope = value["power"]["operating_cases"][0]["downstream_capabilities"][0]["scope"]
        scope["interface_ids"] = ["missing"]
        scope["member_ids_resolved"] = False
        self.assert_error(value, "INVALID_ELECTRICAL_INTERFACE_REFERENCE")

        value = operating_case_record()
        scope = value["power"]["operating_cases"][0]["downstream_capabilities"][0]["scope"]
        scope["named_members"] = ["USB", "USB"]
        self.assert_error(value, "DUPLICATE_ELECTRICAL_NAMED_MEMBER")

        value = operating_case_record()
        scope = value["power"]["operating_cases"][0]["downstream_capabilities"][0]["scope"]
        scope["named_members"] = []
        self.assert_error(value, "UNRESOLVED_ELECTRICAL_SCOPE_MISSING_NAMES")

        value = operating_case_record()
        scope = value["power"]["operating_cases"][0]["downstream_capabilities"][0]["scope"]
        scope["interface_ids"] = ["same", "same"]
        value["interfaces"] = [{"id": "same"}]
        self.assert_error(value, "DUPLICATE_ELECTRICAL_INTERFACE_MEMBER")

    def test_partial_resolution_and_explicit_zero_are_valid(self):
        value = operating_case_record()
        scope = value["power"]["operating_cases"][0]["downstream_capabilities"][0]["scope"]
        scope["interface_ids"] = ["usb-a-1"]
        value["interfaces"] = [{"id": "usb-a-1"}]
        self.assert_valid(value)

        value["power"]["operating_cases"][0]["downstream_capabilities"][0]["current"]["value"] = 0
        self.assert_valid(value)

    def test_dimensionally_wrong_units_are_rejected(self):
        for field, unit in (("voltage", "ampere"), ("current", "volt"), ("power", "milliampere")):
            value = operating_case_record()
            capability = value["power"]["operating_cases"][0]["downstream_capabilities"][0]
            capability.pop("voltage", None)
            capability.pop("current", None)
            capability.pop("power", None)
            capability[field] = {"value": 1, "unit": unit, "precision": "exact"}
            self.assert_error(value, "ELECTRICAL_QUANTITY_UNIT_INVALID")

    def test_duplicate_downstream_semantics_are_rejected(self):
        value = operating_case_record()
        capability = value["power"]["operating_cases"][0]["downstream_capabilities"][0]
        duplicate = copy.deepcopy(capability)
        duplicate["id"] = "usb-output-duplicate"
        value["power"]["operating_cases"][0]["downstream_capabilities"].append(duplicate)
        self.assert_error(value, "DUPLICATE_DOWNSTREAM_CAPABILITY")

        value = operating_case_record()
        duplicate_id = copy.deepcopy(value["power"]["operating_cases"][0]["downstream_capabilities"][0])
        value["power"]["operating_cases"][0]["downstream_capabilities"].append(duplicate_id)
        self.assert_error(value, "DUPLICATE_DOWNSTREAM_CAPABILITY_ID")

    def test_member_order_does_not_change_semantic_identity(self):
        for reorder in ("interface_ids", "named_members"):
            value = operating_case_record()
            case = value["power"]["operating_cases"][0]
            capability = case["downstream_capabilities"][0]
            capability["scope"] = {
                "mode": "aggregate",
                "interface_ids": ["usb-a-1", "usb-a-2", "usb-c-1"],
                "named_members": ["all USB A ports", "USB C port"],
                "member_ids_resolved": True,
                "exhaustive": True,
            }
            duplicate = copy.deepcopy(capability)
            duplicate["id"] = f"usb-output-{reorder}-reordered"
            duplicate["scope"][reorder].reverse()
            case["downstream_capabilities"].append(duplicate)
            value["interfaces"] = [{"id": member} for member in ("usb-a-1", "usb-a-2", "usb-c-1")]
            self.assert_error(value, "DUPLICATE_DOWNSTREAM_CAPABILITY")

        value = operating_case_record()
        case = value["power"]["operating_cases"][0]
        capability = case["downstream_capabilities"][0]
        capability["scope"]["interface_ids"] = ["usb-a-1", "usb-a-2", "usb-c-1"]
        capability["scope"]["named_members"] = ["all USB A ports", "USB C port"]
        capability["scope"]["member_ids_resolved"] = True
        duplicate = copy.deepcopy(capability)
        duplicate["id"] = "usb-output-per-member"
        duplicate["scope"]["mode"] = "per_member"
        case["downstream_capabilities"].append(duplicate)
        value["interfaces"] = [{"id": member} for member in ("usb-a-1", "usb-a-2", "usb-c-1")]
        self.assert_valid(value)

    def test_mixed_scalar_and_range_signatures_are_deterministic(self):
        value = operating_case_record()
        case = value["power"]["operating_cases"][0]
        capability = case["downstream_capabilities"][0]
        capability["scope"] = {
            "mode": "aggregate",
            "interface_ids": ["usb-a-1", "usb-c-1"],
            "named_members": ["all USB A ports", "USB C port"],
            "member_ids_resolved": True,
            "exhaustive": True,
        }
        capability["current"] = {
            "minimum": 0.1,
            "maximum": 0.9,
            "unit": "ampere",
            "precision": "range",
            "semantic_role": "supported_total",
        }
        duplicate = copy.deepcopy(capability)
        duplicate["id"] = "usb-output-reordered"
        duplicate["scope"]["interface_ids"] = ["usb-c-1", "usb-a-1"]
        duplicate["scope"]["named_members"] = ["USB C port", "all USB A ports"]
        case["downstream_capabilities"].append(duplicate)
        value["interfaces"] = [{"id": member} for member in ("usb-a-1", "usb-c-1")]
        self.assert_error(value, "DUPLICATE_DOWNSTREAM_CAPABILITY")

        value = operating_case_record()
        case = value["power"]["operating_cases"][0]
        capability = case["downstream_capabilities"][0]
        capability["current"] = {
            "minimum": 0.1,
            "maximum": 0.9,
            "unit": "ampere",
            "precision": "range",
        }
        distinct = copy.deepcopy(capability)
        distinct["id"] = "usb-output-distinct-shape"
        distinct["voltage"] = {
            "minimum": 4.5,
            "maximum": 5.5,
            "unit": "volt",
            "precision": "range",
        }
        distinct["current"] = {"value": 0.3, "unit": "ampere", "precision": "exact"}
        case["downstream_capabilities"].append(distinct)
        self.assert_valid(value)

    def test_aggregate_and_per_member_limits_can_coexist(self):
        value = operating_case_record()
        case = value["power"]["operating_cases"][0]
        per_member = copy.deepcopy(case["downstream_capabilities"][0])
        per_member["id"] = "usb-per-member"
        per_member["scope"]["mode"] = "per_member"
        per_member["scope"]["interface_ids"] = ["usb-a-1", "usb-a-2"]
        per_member["scope"]["named_members"] = ["USB A 1", "USB A 2"]
        per_member["scope"]["member_ids_resolved"] = False
        per_member["current"]["value"] = 0.9
        case["downstream_capabilities"].append(per_member)
        value["interfaces"] = [{"id": "usb-a-1"}, {"id": "usb-a-2"}]
        self.assert_valid(value)

    def test_multiple_groups_are_valid(self):
        value = operating_case_record()
        case = value["power"]["operating_cases"][0]
        first = case["downstream_capabilities"][0]
        first["scope"] = {"mode": "aggregate", "interface_ids": ["a", "b"], "member_ids_resolved": True, "exhaustive": True}
        second = copy.deepcopy(first)
        second["id"] = "group-cd"
        second["scope"]["interface_ids"] = ["c", "d"]
        second["current"]["value"] = 2
        case["downstream_capabilities"].append(second)
        value["interfaces"] = [{"id": member} for member in ("a", "b", "c", "d")]
        self.assert_valid(value)

    def test_duplicate_semantic_cases_are_rejected(self):
        value = operating_case_record()
        duplicate = copy.deepcopy(value["power"]["operating_cases"][0])
        duplicate["id"] = "duplicate-case"
        value["power"]["operating_cases"].append(duplicate)
        self.assert_error(value, "DUPLICATE_ELECTRICAL_OPERATING_CASE")

    def test_different_operating_contexts_can_have_different_values(self):
        value = operating_case_record()
        value["power"]["operating_cases"][1]["downstream_capabilities"][0]["current"]["value"] = 0.8
        self.assert_valid(value)

    def test_same_scope_and_precision_with_different_values_is_contradictory(self):
        value = operating_case_record()
        case = value["power"]["operating_cases"][0]
        conflicting = copy.deepcopy(case["downstream_capabilities"][0])
        conflicting["id"] = "usb-conflict"
        conflicting["current"]["value"] = 0.4
        case["downstream_capabilities"].append(conflicting)
        self.assert_error(value, "CONTRADICTORY_ELECTRICAL_CAPABILITY")

    def test_range_order_is_validated(self):
        value = operating_case_record()
        capability = value["power"]["operating_cases"][0]["downstream_capabilities"][0]
        capability.pop("voltage")
        capability["power"] = {"minimum": 2, "maximum": 1, "unit": "watt", "precision": "range"}
        self.assert_error(value, "ELECTRICAL_QUANTITY_RANGE_INVALID")

    def test_electrical_strings_are_passive_data(self):
        value = operating_case_record()
        mode = value["power"]["sources"][0]["modes"][0]
        mode["poe"]["standard"] = "__import__('os').system('touch /tmp/avforge')"
        value["power"]["operating_cases"][0]["downstream_capabilities"][0]["resource"] = "$(rm -rf /)"
        value["power"]["operating_cases"][0]["downstream_capabilities"][0]["scope"]["named_members"] = ["<script>alert(1)</script>"]
        self.assert_valid(value)


if __name__ == "__main__":
    unittest.main()
