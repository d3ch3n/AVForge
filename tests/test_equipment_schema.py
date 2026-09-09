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


def with_electrical(record, electrical_characteristics):
    value = copy.deepcopy(record)
    value["interfaces"][0]["electrical_characteristics"] = electrical_characteristics
    return value


def electrical_record(electrical_characteristics):
    return with_electrical(load_record("equipment/qsys/core-8-flex.json"), electrical_characteristics)


class EquipmentSchemaV37Tests(unittest.TestCase):
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

    def test_e01_interface_without_electrical_characteristics(self):
        self.assert_valid(load_record("equipment/qsys/core-8-flex.json"))

    def test_e02_input_profile_minimum(self):
        self.assert_valid(electrical_record({"input": {}}))

    def test_e03_output_profile_minimum(self):
        self.assert_valid(electrical_record({"output": {}}))

    def test_e04_bidirectional_profiles(self):
        self.assert_valid(electrical_record({"input": {}, "output": {}}))

    def test_e05_balanced_mode(self):
        self.assert_valid(electrical_record({"input": {"balance_modes": ["balanced"]}}))

    def test_e06_unbalanced_mode(self):
        self.assert_valid(electrical_record({"input": {"balance_modes": ["unbalanced"]}}))

    def test_e07_both_balance_modes(self):
        self.assert_valid(electrical_record({"input": {"balance_modes": ["balanced", "unbalanced"]}}))

    def test_e08_mic_level_class(self):
        self.assert_valid(electrical_record({"input": {"operating_level_classes": ["mic"]}}))

    def test_e09_line_level_class(self):
        self.assert_valid(electrical_record({"input": {"operating_level_classes": ["line"]}}))

    def test_e10_mic_line_level_classes(self):
        self.assert_valid(electrical_record({"input": {"operating_level_classes": ["mic", "line"]}}))

    def test_e11_negative_dBu_nominal_level(self):
        self.assert_valid(electrical_record({"input": {"nominal_levels": [{"value": -10, "unit": "decibel-u"}]}}))

    def test_e12_input_phantom_provision(self):
        self.assert_valid(electrical_record({"input": {"phantom_power": {"provision": {"supported": True, "voltage": {"value": 48, "unit": "volt"}, "current_max": {"value": 10, "unit": "milliampere"}}}}}))

    def test_e13_output_phantom_requirement(self):
        self.assert_valid(electrical_record({"output": {"phantom_power": {"requirement": {"required": True}}}}))

    def test_e14_output_phantom_tolerance_false(self):
        self.assert_valid(electrical_record({"output": {"phantom_power": {"tolerance": {"supported": False}}}}))

    def test_e15_output_minimum_load_impedance(self):
        self.assert_valid(electrical_record({"output": {"minimum_load_impedance": {"value": 600, "unit": "ohm"}}}))

    def test_e16_empty_balance_modes(self):
        self.assert_invalid(electrical_record({"input": {"balance_modes": []}}))

    def test_e17_duplicate_balance_modes(self):
        self.assert_invalid(electrical_record({"input": {"balance_modes": ["balanced", "balanced"]}}))

    def test_e18_unknown_balance_mode(self):
        self.assert_invalid(electrical_record({"input": {"balance_modes": ["both"]}}))

    def test_e19_empty_level_classes(self):
        self.assert_invalid(electrical_record({"input": {"operating_level_classes": []}}))

    def test_e20_unknown_level_class(self):
        self.assert_invalid(electrical_record({"input": {"operating_level_classes": ["instrument"]}}))

    def test_e21_input_phantom_requirement(self):
        self.assert_invalid(electrical_record({"input": {"phantom_power": {"requirement": {"required": True}}}}))

    def test_e22_input_phantom_tolerance(self):
        self.assert_invalid(electrical_record({"input": {"phantom_power": {"tolerance": {"supported": True}}}}))

    def test_e23_output_phantom_provision(self):
        self.assert_invalid(electrical_record({"output": {"phantom_power": {"provision": {"supported": True}}}}))

    def test_e24_phantom_prohibits(self):
        self.assert_invalid(electrical_record({"output": {"phantom_power": {"prohibits": True}}}))

    def test_e25_phantom_enabled(self):
        self.assert_invalid(electrical_record({"output": {"phantom_power": {"enabled": True}}}))

    def test_e26_input_minimum_load_impedance(self):
        self.assert_invalid(electrical_record({"input": {"minimum_load_impedance": {"value": 600, "unit": "ohm"}}}))

    def test_e27_measurement_without_value(self):
        self.assert_invalid(electrical_record({"input": {"nominal_levels": [{"unit": "volt-rms"}]}}))

    def test_e28_measurement_without_unit(self):
        self.assert_invalid(electrical_record({"input": {"nominal_levels": [{"value": 1}]}}))

    def test_e29_negative_impedance(self):
        self.assert_invalid(electrical_record({"input": {"impedance": {"nominal": {"value": -1, "unit": "ohm"}}}}))

    def test_e30_negative_phantom_voltage(self):
        self.assert_invalid(electrical_record({"input": {"phantom_power": {"provision": {"supported": True, "voltage": {"value": -48, "unit": "volt"}}}}}))

    def test_e31_negative_phantom_current(self):
        self.assert_invalid(electrical_record({"input": {"phantom_power": {"provision": {"supported": True, "current_max": {"value": -1, "unit": "ampere"}}}}}))

    def test_e32_unknown_electrical_property(self):
        self.assert_invalid(electrical_record({"other": {"value": True}}))

    def test_e33_valid_input_variant_balanced(self):
        self.assert_valid(electrical_record({"input": {"balance_modes": ["balanced"], "variants": [{"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}]}}))

    def test_e34_valid_output_variant_unbalanced(self):
        self.assert_valid(electrical_record({"output": {"balance_modes": ["unbalanced"], "variants": [{"conditions": {"balance_mode": "unbalanced"}, "impedance": {"nominal": {"value": 100, "unit": "ohm"}}}]}}))

    def test_e35_valid_variant_with_maximum_level(self):
        self.assert_valid(electrical_record({"output": {"variants": [{"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}]}}))

    def test_e36_valid_variant_with_impedance_nominal(self):
        self.assert_valid(electrical_record({"input": {"variants": [{"conditions": {"balance_mode": "balanced"}, "impedance": {"nominal": {"value": 200, "unit": "ohm"}}}]}}))

    def test_e37_valid_impedance_upper_bound_open(self):
        self.assert_valid(electrical_record({"output": {"impedance": {"upper_bound": {"value": 100, "unit": "ohm", "inclusive": False}}}}))

    def test_e38_valid_impedance_upper_bound_inclusive(self):
        self.assert_valid(electrical_record({"output": {"impedance": {"upper_bound": {"value": 100, "unit": "ohm", "inclusive": True}}}}))

    def test_e39_invalid_condition_unknown_property(self):
        self.assert_invalid(electrical_record({"input": {"variants": [{"conditions": {"operating_level_class": "line"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}]}}))

    def test_e40_invalid_balance_mode_enum(self):
        self.assert_invalid(electrical_record({"input": {"variants": [{"conditions": {"balance_mode": "both"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}]}}))

    # E41 SEMANTIC_VALIDATOR_PENDING: duplicate balance_mode variants are cross-object semantics.
    # E42 SEMANTIC_VALIDATOR_PENDING: condition membership in profile.balance_modes is cross-object semantics.

    def test_e43_invalid_upper_bound_missing_inclusive(self):
        self.assert_invalid(electrical_record({"output": {"impedance": {"upper_bound": {"value": 100, "unit": "ohm"}}}}))

    def test_e44_invalid_upper_bound_negative_value(self):
        self.assert_invalid(electrical_record({"output": {"impedance": {"upper_bound": {"value": -1, "unit": "ohm", "inclusive": False}}}}))

    def test_e45_invalid_unknown_upper_bound_property(self):
        self.assert_invalid(electrical_record({"output": {"impedance": {"upper_bound": {"value": 100, "unit": "ohm", "inclusive": False, "operator": "<"}}}}))

    def test_e46_invalid_phantom_inside_variant(self):
        self.assert_invalid(electrical_record({"input": {"variants": [{"conditions": {"balance_mode": "balanced"}, "phantom_power": {"provision": {"supported": True}}}]}}))

    def test_e47_valid_base_property_plus_unrelated_conditional_property(self):
        self.assert_valid(electrical_record({"output": {"impedance": {"nominal": {"value": 100, "unit": "ohm"}}, "variants": [{"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}]}}))

    # E48 SEMANTIC_VALIDATOR_PENDING: base and conditional values for one property require cross-object semantics.

    def test_e49_valid_existing_schema_35_shaped_record_unchanged(self):
        self.assert_valid(load_record("equipment/crestron/dm-nvx-360c.json"))

    def test_e50_valid_partial_variant_coverage(self):
        self.assert_valid(electrical_record({"output": {"balance_modes": ["balanced", "unbalanced"], "variants": [{"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}}]}}))

    def test_e51_invalid_unknown_variant_property(self):
        self.assert_invalid(electrical_record({"output": {"variants": [{"conditions": {"balance_mode": "balanced"}, "operating_level_classes": ["line"]}]}}))

    def test_e52_valid_core_8_flex_unchanged(self):
        self.assert_valid(load_record("equipment/qsys/core-8-flex.json"))

    def test_e53_valid_future_dm_nvx_shape(self):
        self.assert_valid(electrical_record({"output": {"balance_modes": ["balanced", "unbalanced"], "operating_level_classes": ["line"], "variants": [
            {"conditions": {"balance_mode": "balanced"}, "impedance": {"nominal": {"value": 200, "unit": "ohm"}}, "maximum_level": {"value": 4, "unit": "volt-rms"}},
            {"conditions": {"balance_mode": "unbalanced"}, "impedance": {"nominal": {"value": 100, "unit": "ohm"}}, "maximum_level": {"value": 2, "unit": "volt-rms"}}
        ]}}))

    def test_e54_valid_future_hd_md_shape(self):
        self.assert_valid(electrical_record({"output": {"balance_modes": ["balanced", "unbalanced"], "operating_level_classes": ["line"], "impedance": {"upper_bound": {"value": 100, "unit": "ohm", "inclusive": False}}, "variants": [
            {"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}},
            {"conditions": {"balance_mode": "unbalanced"}, "maximum_level": {"value": 2, "unit": "volt-rms"}}
        ]}}))

    def test_e55_all_equipment_records_remain_valid(self):
        for path in sorted((ROOT / "equipment").glob("**/*.json")):
            self.assert_valid(json.loads(path.read_text()))

    def test_e56_invalid_variant_with_empty_impedance_payload(self):
        self.assert_invalid(electrical_record({"output": {"variants": [{"conditions": {"balance_mode": "balanced"}, "impedance": {}}]}}))

    def test_p01_interface_without_physical_connection_capabilities(self):
        self.assert_valid(load_record("equipment/qsys/core-8-flex.json"))

    def test_p02_empty_physical_connection_capabilities_is_valid(self):
        record = load_record("equipment/qsys/core-8-flex.json")
        record["interfaces"][0]["physical_connection_capabilities"] = {}
        self.assert_valid(record)

    def test_p03_passive_interconnection_supported(self):
        record = load_record("equipment/qsys/core-8-flex.json")
        record["interfaces"][0]["physical_connection_capabilities"] = {
            "passive_interconnection": {"status": "supported"}
        }
        self.assert_valid(record)

    def test_p04_passive_interconnection_unsupported(self):
        record = load_record("equipment/qsys/core-8-flex.json")
        record["interfaces"][0]["physical_connection_capabilities"] = {
            "passive_interconnection": {"status": "unsupported"}
        }
        self.assert_valid(record)

    def test_p05_status_boolean_true_invalid(self):
        record = load_record("equipment/qsys/core-8-flex.json")
        record["interfaces"][0]["physical_connection_capabilities"] = {
            "passive_interconnection": {"status": True}
        }
        self.assert_invalid(record)

    def test_p06_status_boolean_false_invalid(self):
        record = load_record("equipment/qsys/core-8-flex.json")
        record["interfaces"][0]["physical_connection_capabilities"] = {
            "passive_interconnection": {"status": False}
        }
        self.assert_invalid(record)

    def test_p07_status_unknown_invalid(self):
        record = load_record("equipment/qsys/core-8-flex.json")
        record["interfaces"][0]["physical_connection_capabilities"] = {
            "passive_interconnection": {"status": "unknown"}
        }
        self.assert_invalid(record)

    def test_p08_status_compatible_invalid(self):
        record = load_record("equipment/qsys/core-8-flex.json")
        record["interfaces"][0]["physical_connection_capabilities"] = {
            "passive_interconnection": {"status": "compatible"}
        }
        self.assert_invalid(record)

    def test_p09_passive_interconnection_boolean_true_invalid(self):
        record = load_record("equipment/qsys/core-8-flex.json")
        record["interfaces"][0]["physical_connection_capabilities"] = {
            "passive_interconnection": True
        }
        self.assert_invalid(record)

    def test_p10_passive_interconnection_boolean_false_invalid(self):
        record = load_record("equipment/qsys/core-8-flex.json")
        record["interfaces"][0]["physical_connection_capabilities"] = {
            "passive_interconnection": False
        }
        self.assert_invalid(record)

    def test_p11_empty_passive_interconnection_invalid(self):
        record = load_record("equipment/qsys/core-8-flex.json")
        record["interfaces"][0]["physical_connection_capabilities"] = {
            "passive_interconnection": {}
        }
        self.assert_invalid(record)

    def test_p12_unknown_passive_interconnection_field_invalid(self):
        record = load_record("equipment/qsys/core-8-flex.json")
        record["interfaces"][0]["physical_connection_capabilities"] = {
            "passive_interconnection": {
                "status": "supported",
                "notes": "not supported in Schema 3.7"
            }
        }
        self.assert_invalid(record)

    def test_p13_unknown_physical_connection_capabilities_field_invalid(self):
        record = load_record("equipment/qsys/core-8-flex.json")
        record["interfaces"][0]["physical_connection_capabilities"] = {
            "direct_mating": {"status": "supported"}
        }
        self.assert_invalid(record)


def low_impedance_load(value=8, unit="ohm"):
    return {"type": "low_impedance", "impedance": {"value": value, "unit": unit}}


def constant_voltage_load(value=70, unit="volt"):
    return {"type": "constant_voltage", "voltage": {"value": value, "unit": unit}}


def power_rating(rating_type="maximum", value=1000, unit="watt"):
    return {"type": rating_type, "power": {"value": value, "unit": unit}}


def operating_point(point_id="op-1", load=None, ratings=None):
    return {
        "id": point_id,
        "load": load if load is not None else low_impedance_load(),
        "ratings": ratings if ratings is not None else [power_rating()],
    }


def amplifier_capability(cap_id="amp-1", topology="independent", groups=None, points=None, notes=None):
    capability = {
        "id": cap_id,
        "topology": topology,
        "member_groups": groups if groups is not None else [["output-a"]],
        "operating_points": points if points is not None else [operating_point()],
    }
    if notes is not None:
        capability["notes"] = notes
    return capability


def amplifier_record(capabilities):
    value = copy.deepcopy(load_record("equipment/qsys/core-8-flex.json"))
    value["amplifier_output_capabilities"] = capabilities
    return value


class EquipmentSchemaV38Tests(unittest.TestCase):
    def assert_valid(self, record):
        self.assertEqual(list(VALIDATOR.iter_errors(record)), [])

    def assert_invalid(self, record):
        self.assertTrue(list(VALIDATOR.iter_errors(record)))

    def test_a00_record_without_amplifier_capabilities_is_valid(self):
        self.assert_valid(load_record("equipment/qsys/core-8-flex.json"))

    def test_a01_valid_independent_low_impedance(self):
        self.assert_valid(amplifier_record([amplifier_capability(
            topology="independent",
            groups=[["output-a"]],
            points=[operating_point(ratings=[power_rating("maximum", 1000), power_rating("continuous", 300)])],
        )]))

    def test_a02_valid_bridge_constant_voltage(self):
        self.assert_valid(amplifier_record([amplifier_capability(
            cap_id="amp-bridge",
            topology="bridge",
            groups=[["output-a", "output-b"]],
            points=[operating_point("op-140v", constant_voltage_load(140))],
        )]))

    def test_a03_valid_parallel_with_three_members(self):
        self.assert_valid(amplifier_record([amplifier_capability(
            cap_id="amp-parallel",
            topology="parallel",
            groups=[["output-a", "output-b", "output-c"]],
        )]))

    def test_a04_valid_bridge_parallel_with_four_members(self):
        self.assert_valid(amplifier_record([amplifier_capability(
            cap_id="amp-bridge-parallel",
            topology="bridge_parallel",
            groups=[["output-a", "output-b", "output-c", "output-d"]],
        )]))

    def test_a05_valid_unknown_rating_type_is_structural(self):
        self.assert_valid(amplifier_record([amplifier_capability(
            points=[operating_point(ratings=[power_rating("peak", 1200)])],
        )]))

    def test_a06_invalid_missing_capability_id(self):
        capability = amplifier_capability()
        del capability["id"]
        self.assert_invalid(amplifier_record([capability]))

    def test_a07_invalid_missing_topology(self):
        capability = amplifier_capability()
        del capability["topology"]
        self.assert_invalid(amplifier_record([capability]))

    def test_a08_invalid_missing_member_groups(self):
        capability = amplifier_capability()
        del capability["member_groups"]
        self.assert_invalid(amplifier_record([capability]))

    def test_a09_invalid_empty_member_groups(self):
        self.assert_invalid(amplifier_record([amplifier_capability(groups=[])]))

    def test_a10_invalid_empty_member_group(self):
        self.assert_invalid(amplifier_record([amplifier_capability(groups=[[]])]))

    def test_a11_invalid_unknown_topology(self):
        self.assert_invalid(amplifier_record([amplifier_capability(topology="fast")]))

    def test_a12_invalid_missing_operating_points(self):
        capability = amplifier_capability()
        del capability["operating_points"]
        self.assert_invalid(amplifier_record([capability]))

    def test_a13_invalid_empty_operating_points(self):
        self.assert_invalid(amplifier_record([amplifier_capability(points=[])]))

    def test_a14_invalid_low_impedance_without_impedance(self):
        self.assert_invalid(amplifier_record([amplifier_capability(
            points=[operating_point(load={"type": "low_impedance"})],
        )]))

    def test_a15_invalid_low_impedance_with_voltage(self):
        load = low_impedance_load()
        load["voltage"] = {"value": 70, "unit": "volt"}
        self.assert_invalid(amplifier_record([amplifier_capability(points=[operating_point(load=load)])]))

    def test_a16_invalid_constant_voltage_without_voltage(self):
        self.assert_invalid(amplifier_record([amplifier_capability(
            points=[operating_point(load={"type": "constant_voltage"})],
        )]))

    def test_a17_invalid_constant_voltage_with_impedance(self):
        load = constant_voltage_load()
        load["impedance"] = {"value": 8, "unit": "ohm"}
        self.assert_invalid(amplifier_record([amplifier_capability(points=[operating_point(load=load)])]))

    def test_a18_invalid_load_with_both_voltage_and_impedance(self):
        self.assert_invalid(amplifier_record([amplifier_capability(
            points=[operating_point(load={"type": "low_impedance", "impedance": {"value": 8, "unit": "ohm"}, "voltage": {"value": 70, "unit": "volt"}})],
        )]))

    def test_a19_invalid_negative_impedance(self):
        self.assert_invalid(amplifier_record([amplifier_capability(
            points=[operating_point(load=low_impedance_load(value=-8))],
        )]))

    def test_a20_invalid_negative_voltage(self):
        self.assert_invalid(amplifier_record([amplifier_capability(
            points=[operating_point(load=constant_voltage_load(value=-70))],
        )]))

    def test_a21_invalid_rating_missing_type(self):
        rating = power_rating()
        del rating["type"]
        self.assert_invalid(amplifier_record([amplifier_capability(points=[operating_point(ratings=[rating])])]))

    def test_a22_invalid_rating_missing_power(self):
        rating = power_rating()
        del rating["power"]
        self.assert_invalid(amplifier_record([amplifier_capability(points=[operating_point(ratings=[rating])])]))

    def test_a23_invalid_negative_power(self):
        self.assert_invalid(amplifier_record([amplifier_capability(
            points=[operating_point(ratings=[power_rating(value=-100)])],
        )]))

    def test_a24_invalid_extra_properties_rejected(self):
        capability = amplifier_capability(notes="FAST provenance")
        capability["wiring_class"] = "Class 2"
        self.assert_invalid(amplifier_record([capability]))

    def test_a25_valid_all_existing_records_remain_valid(self):
        for path in sorted((ROOT / "equipment").glob("**/*.json")):
            self.assert_valid(json.loads(path.read_text()))


if __name__ == "__main__":
    unittest.main()
