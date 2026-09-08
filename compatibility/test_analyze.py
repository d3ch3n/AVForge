import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from compatibility.analyze import AnalysisInputError, analyze, main


ROOT = Path(__file__).resolve().parents[1]


def load_record(path):
    return json.loads((ROOT / path).read_text())


def equipment(equipment_id, interface_id="a", signal=None, connector="hdmi-type-a", gender="female", **extra):
    interface = {
        "id": interface_id,
        "label": interface_id,
        "direction": "bidirectional",
        "connector": connector,
        "connector_gender": gender,
    }
    if signal is not None:
        interface["signals"] = [signal]
    interface.update(extra.pop("interface", {}))
    record = {"id": equipment_id, "manufacturer": equipment_id, "model": equipment_id, "interfaces": [interface]}
    record.update(extra)
    return record


def signal(signal_type="video", signal_family="hdmi", direction="bidirectional", protocol_family=None, **characteristics):
    value = {
        "id": "signal",
        "name": "signal",
        "signal_type": signal_type,
        "signal_family": signal_family,
        "direction": direction,
    }
    if protocol_family is not None:
        value["protocol_family"] = protocol_family
    if characteristics:
        value["signal_characteristics"] = characteristics
    return value


def request(function, assumption="APPROPRIATE_MEDIUM", source_id="source", target_id="target"):
    return {
        "source": {"equipment_id": source_id, "interface_id": "a"},
        "target": {"equipment_id": target_id, "interface_id": "a"},
        "requested_function": function,
        "analysis_scope": "CATALOG",
        "interconnect_assumption": assumption,
    }


class CompatibilityAnalyzerTests(unittest.TestCase):
    def analyze(self, function, source=None, target=None, **kwargs):
        source = source or equipment("source", signal=signal())
        target = target or equipment("target", signal=signal())
        return analyze(request(function, **kwargs), [source, target])

    def test_ac01_explicit_compatible_signal(self):
        result = self.analyze({"signal_family": "hdmi"})
        self.assertEqual(result["result"], "COMPATIBLE")

    def test_ac02_explicit_incompatible_signal(self):
        result = self.analyze({"signal_family": "hdmi"}, target=equipment("target", signal=signal(signal_family="analog-audio")))
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_ac03_missing_signal_data(self):
        result = self.analyze({"signal_family": "hdmi"}, target=equipment("target"))
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac04_explicit_common_protocol(self):
        records = [equipment("source", signal=signal(protocol_family="rs-232")), equipment("target", signal=signal(protocol_family="rs-232"))]
        result = analyze(request({"protocol_family": "rs-232"}), records)
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")

    def test_ac05_incompatible_protocol(self):
        records = [equipment("source", signal=signal(protocol_family="rs-232")), equipment("target", signal=signal(protocol_family="usb"))]
        result = analyze(request({"protocol_family": "rs-232"}), records)
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_ac06_undeclared_protocol(self):
        result = self.analyze({"protocol_family": "aes67"})
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac07_ethernet_does_not_imply_aes67(self):
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"))
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"))
        result = self.analyze({"protocol_family": "aes67"}, source=source, target=target)
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac08_ethernet_does_not_imply_dante(self):
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"))
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"))
        result = self.analyze({"protocol_family": "dante"}, source=source, target=target)
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac09_output_to_input(self):
        source = equipment("source", signal=signal(direction="output"))
        target = equipment("target", signal=signal(direction="input"))
        result = self.analyze({"signal_family": "hdmi"}, source=source, target=target)
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")

    def test_ac10_input_to_input(self):
        source = equipment("source", signal=signal(direction="input"))
        target = equipment("target", signal=signal(direction="input"))
        self.assertEqual(self.analyze({"signal_family": "hdmi"}, source=source, target=target)["result"], "INCOMPATIBLE")

    def test_ac11_output_to_output(self):
        source = equipment("source", signal=signal(direction="output"))
        target = equipment("target", signal=signal(direction="output"))
        self.assertEqual(self.analyze({"signal_family": "hdmi"}, source=source, target=target)["result"], "INCOMPATIBLE")

    def test_ac12_bidirectional_is_conservative_but_usable(self):
        result = self.analyze({"signal_family": "hdmi"})
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")

    def test_ac13_configurable_mode_is_conditional(self):
        source = equipment(
            "source",
            signal=signal(direction="bidirectional", configurable_role="input or output"),
        )
        result = self.analyze({"signal_family": "hdmi"}, source=source)
        self.assertEqual(result["layers"]["direction"]["result"], "CONDITIONALLY_COMPATIBLE")

    def test_ac14_irrelevant_electrical_is_not_applicable(self):
        result = self.analyze({"protocol_family": "aes67"})
        self.assertFalse(result["layers"]["electrical"]["applicable"])

    def test_ac15_required_electrical_missing(self):
        source = equipment("source", signal=signal(signal_type="audio", signal_family="analog-audio", direction="output", balanced=True))
        target = equipment("target", signal=signal(signal_type="audio", signal_family="analog-audio", direction="input"))
        result = self.analyze({"signal_family": "analog-audio"}, source=source, target=target)
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac16_explicit_deny(self):
        source = equipment("source", signal=signal(), interface={"connection_constraints": {"id": "deny", "denied_targets": {"targets": [{"equipment_id": "target"}]}}})
        result = self.analyze({"signal_family": "hdmi"}, source=source)
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_ac17_no_restriction_is_not_applicable(self):
        result = self.analyze({"signal_family": "hdmi"})
        self.assertFalse(result["layers"]["restrictions"]["applicable"])

    def test_ac18_capacity_absent_is_not_applicable(self):
        result = self.analyze({"protocol_family": "rs-232"})
        self.assertFalse(result["layers"]["capacity"]["applicable"])

    def test_ac19_capacity_sufficient(self):
        capability = {"id": "cap", "type": "data", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}, "capacity": {"rx_channels": 8}}
        records = [equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability]), equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])]
        result = analyze(request({"protocol_family": "rs-232", "capacity_requirement": {"rx_channels": 4}}), records)
        self.assertEqual(result["layers"]["capacity"]["result"], "COMPATIBLE")

    def test_ac20_capacity_insufficient(self):
        capability = {"id": "cap", "type": "data", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}, "capacity": {"rx_channels": 2}}
        records = [equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability]), equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])]
        self.assertEqual(analyze(request({"protocol_family": "rs-232", "capacity_requirement": {"rx_channels": 4}}), records)["result"], "INCOMPATIBLE")

    def test_ac21_capacity_unknown(self):
        result = self.analyze({"protocol_family": "rs-232", "capacity_requirement": {"rx_channels": 4}})
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac22_incompatible_precedes_everything(self):
        source = equipment("source", signal=signal(direction="input"))
        result = self.analyze({"signal_family": "hdmi"}, source=source)
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_ac23_insufficient_precedes_condition(self):
        source = equipment("source", signal=signal(signal_type="audio", signal_family="analog-audio", direction="bidirectional", configurable_role="input or output"))
        target = equipment("target", signal=signal(signal_type="audio", signal_family="analog-audio", direction="bidirectional"))
        result = self.analyze({"signal_family": "analog-audio"}, source=source, target=target)
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac24_evidence_does_not_override_deny(self):
        source = equipment(
            "source",
            signal=signal(protocol_family="rs-232"),
            interface={"connection_constraints": {"id": "deny", "denied_targets": {"targets": [{"equipment_id": "target"}]}}},
            known_compatibilities=[{"id": "known", "relation": "compatible", "target_equipment_id": "target", "local_interface_id": "a", "protocol_family": "rs-232"}],
        )
        result = self.analyze({"protocol_family": "rs-232"}, source=source)
        self.assertEqual(result["result"], "INCOMPATIBLE")
        self.assertTrue(result["evidence"])

    def test_ac25_incompatible_is_not_execution_error(self):
        source = equipment("source", signal=signal(direction="input"))
        target = equipment("target", signal=signal(direction="input"))
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.json"
            target_path = Path(directory) / "target.json"
            source_path.write_text(json.dumps(source))
            target_path.write_text(json.dumps(target))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main([
                    "--equipment", str(source_path), str(target_path),
                    "--source-equipment", "source", "--source-interface", "a",
                    "--target-equipment", "target", "--target-interface", "a",
                    "--requested-function", '{"signal_family":"hdmi"}',
                    "--analysis-scope", "CATALOG",
                    "--interconnect-assumption", "APPROPRIATE_MEDIUM",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["result"], "INCOMPATIBLE")

    def test_physical_direct_female_pair_is_incompatible(self):
        result = self.analyze({"signal_family": "hdmi"}, assumption="DIRECT")
        self.assertEqual(result["layers"]["physical"]["result"], "INCOMPATIBLE")

    def test_physical_appropriate_medium_female_pair_is_compatible(self):
        result = self.analyze({"signal_family": "hdmi"}, assumption="APPROPRIATE_MEDIUM")
        self.assertEqual(result["layers"]["physical"]["result"], "COMPATIBLE")

    def test_physical_different_connectors_do_not_assume_converter(self):
        source = equipment("source", signal=signal(signal_family="hdmi"), connector="hdmi-type-a")
        target = equipment("target", signal=signal(signal_family="hdmi"), connector="usb-type-c")
        result = self.analyze({"signal_family": "hdmi"}, source=source, target=target)
        self.assertEqual(result["layers"]["physical"]["result"], "INSUFFICIENT_DATA")

    def test_invalid_request_is_explicit_error(self):
        with self.assertRaises(AnalysisInputError):
            self.analyze({})

    def test_ac37_protocol_absent_coverage_absent(self):
        result = self.analyze({"protocol_family": "aes67"})
        self.assertEqual(result["layers"]["protocol"]["result"], "INSUFFICIENT_DATA")

    def test_ac38_communication_protocol_coverage_absent(self):
        source = equipment("source", signal=signal(), catalog_coverage={})
        result = self.analyze({"protocol_family": "aes67"}, source=source)
        self.assertEqual(result["layers"]["protocol"]["result"], "INSUFFICIENT_DATA")

    def test_ac39_protocol_absent_coverage_false(self):
        coverage = {"communication_protocols": {"complete": False}}
        source = equipment("source", signal=signal(), catalog_coverage=coverage)
        target = equipment("target", signal=signal(), catalog_coverage=coverage)
        result = self.analyze({"protocol_family": "aes67"}, source=source, target=target)
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac40_protocol_absent_coverage_true(self):
        coverage = {"communication_protocols": {"complete": True}}
        source = equipment("source", signal=signal(), catalog_coverage=coverage)
        target = equipment("target", signal=signal(), catalog_coverage=coverage)
        result = self.analyze({"protocol_family": "aes67"}, source=source, target=target)
        self.assertEqual(result["layers"]["protocol"]["result"], "INCOMPATIBLE")

    def test_ac41_protocol_present_coverage_true_analyzes_normally(self):
        coverage = {"communication_protocols": {"complete": True}}
        source = equipment("source", signal=signal(protocol_family="rs-232"), catalog_coverage=coverage)
        target = equipment("target", signal=signal(protocol_family="rs-232"), catalog_coverage=coverage)
        result = self.analyze({"protocol_family": "rs-232"}, source=source, target=target)
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")

    def test_ac42_protocol_present_coverage_false_analyzes_normally(self):
        coverage = {"communication_protocols": {"complete": False}}
        source = equipment("source", signal=signal(protocol_family="rs-232"), catalog_coverage=coverage)
        target = equipment("target", signal=signal(protocol_family="rs-232"), catalog_coverage=coverage)
        result = self.analyze({"protocol_family": "rs-232"}, source=source, target=target)
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")

    def test_ac43_protocol_present_coverage_absent_analyzes_normally(self):
        source = equipment("source", signal=signal(protocol_family="rs-232"))
        target = equipment("target", signal=signal(protocol_family="rs-232"))
        result = self.analyze({"protocol_family": "rs-232"}, source=source, target=target)
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")

    def test_ac44_coverage_does_not_apply_without_protocol_request(self):
        source = equipment("source", signal=signal(), catalog_coverage={"communication_protocols": {"complete": True}})
        target = equipment("target", signal=signal(), catalog_coverage={"communication_protocols": {"complete": True}})
        result = self.analyze({"signal_family": "hdmi"}, source=source, target=target)
        self.assertFalse(result["layers"]["protocol"]["applicable"])
        self.assertEqual(result["result"], "COMPATIBLE")

    def test_ac45_positive_evidence_does_not_override_complete_coverage(self):
        source = equipment(
            "source",
            signal=signal(),
            catalog_coverage={"communication_protocols": {"complete": True}},
            known_compatibilities=[{"id": "known", "relation": "compatible", "target_equipment_id": "target", "local_interface_id": "a", "protocol_family": "aes67"}],
        )
        target = equipment("target", signal=signal())
        result = self.analyze({"protocol_family": "aes67"}, source=source, target=target)
        self.assertEqual(result["result"], "INCOMPATIBLE")
        self.assertTrue(result["evidence"])

    def test_ac46_present_protocol_unavailable(self):
        capability = {"id": "cap", "type": "data", "protocol_family": "rs-232", "direction": "bidirectional", "availability": "unavailable", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        records = [equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability]), equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])]
        self.assertEqual(analyze(request({"protocol_family": "rs-232"}), records)["result"], "INCOMPATIBLE")

    def test_ac47_present_protocol_assignment_excludes_interface(self):
        capability = {"id": "cap", "type": "data", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["b"]}}
        source = equipment("source", signal=signal(protocol_family="rs-232"))
        target = equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface={"id": "b", "label": "b"})
        target["interfaces"].append({"id": "a", "label": "a", "direction": "bidirectional", "connector": "hdmi-type-a", "connector_gender": "female", "signals": [signal(protocol_family="rs-232")]})
        self.assertEqual(self.analyze({"protocol_family": "rs-232"}, source=source, target=target)["result"], "INCOMPATIBLE")

    def test_ac48_present_protocol_configurable_allowed(self):
        capability = {"id": "cap", "type": "data", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "configurable", "allowed_interface_ids": ["a"]}}
        records = [equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability]), equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])]
        self.assertEqual(analyze(request({"protocol_family": "rs-232"}), records)["result"], "CONDITIONALLY_COMPATIBLE")

    def test_ac49_complete_coverage_precedes_other_compatible_layers(self):
        coverage = {"communication_protocols": {"complete": True}}
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c", catalog_coverage=coverage)
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c", catalog_coverage=coverage)
        result = self.analyze({"protocol_family": "dante"}, source=source, target=target)
        self.assertEqual(result["layers"]["physical"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_ac50_incomplete_coverage_keeps_unknown_result(self):
        coverage = {"communication_protocols": {"complete": False}}
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c", catalog_coverage=coverage)
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c", catalog_coverage=coverage)
        result = self.analyze({"protocol_family": "dante"}, source=source, target=target)
        self.assertEqual(result["layers"]["physical"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac51_protocol_coverage_does_not_change_electrical_layer(self):
        coverage = {"communication_protocols": {"complete": True}}
        source = equipment("source", signal=signal(signal_type="audio", signal_family="analog-audio", direction="output", balanced=True), catalog_coverage=coverage)
        target = equipment("target", signal=signal(signal_type="audio", signal_family="analog-audio", direction="input", balanced=True), catalog_coverage=coverage)
        result = self.analyze({"signal_family": "analog-audio"}, source=source, target=target)
        self.assertEqual(result["layers"]["electrical"]["result"], "COMPATIBLE")

    def test_ac52_protocol_coverage_does_not_change_signal_layer(self):
        coverage = {"communication_protocols": {"complete": True}}
        source = equipment("source", signal=signal(), catalog_coverage=coverage)
        target = equipment("target", signal=signal(), catalog_coverage=coverage)
        result = self.analyze({"signal_family": "hdmi"}, source=source, target=target)
        self.assertEqual(result["layers"]["signal"]["result"], "COMPATIBLE")

    def test_ac53_protocol_coverage_does_not_change_capacity_layer(self):
        coverage = {"communication_protocols": {"complete": True}}
        capability = {"id": "cap", "type": "data", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}, "capacity": {"rx_channels": 8}}
        records = [equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], catalog_coverage=coverage), equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], catalog_coverage=coverage)]
        result = analyze(request({"protocol_family": "rs-232", "capacity_requirement": {"rx_channels": 4}}), records)
        self.assertEqual(result["layers"]["capacity"]["result"], "COMPATIBLE")

    def test_ac54_chassis_coverage_does_not_infer_module_protocols(self):
        chassis = load_record("equipment/crestron/dmf-ci-8.json")
        chassis["catalog_coverage"] = {"communication_protocols": {"complete": True}}
        module = load_record("equipment/crestron/dm-nvx-360c.json")
        request_value = {"source": {"equipment_id": chassis["id"], "interface_id": "console-serial"}, "target": {"equipment_id": module["id"], "interface_id": "ethernet-1"}, "requested_function": {"protocol_family": "dm-nvx"}, "analysis_scope": "CATALOG", "interconnect_assumption": "APPROPRIATE_MEDIUM"}
        result = analyze(request_value, [chassis, module])
        self.assertEqual(result["layers"]["protocol"]["result"], "INCOMPATIBLE")

    def test_ac55_module_coverage_is_independent_of_chassis(self):
        module = load_record("equipment/crestron/dm-nvx-360c.json")
        module["catalog_coverage"] = {"communication_protocols": {"complete": True}}
        module_request = {"source": {"equipment_id": module["id"], "interface_id": "ethernet-1"}, "target": {"equipment_id": module["id"], "interface_id": "ethernet-1"}, "requested_function": {"protocol_family": "dm-nvx"}, "analysis_scope": "CATALOG", "interconnect_assumption": "APPROPRIATE_MEDIUM"}
        result = analyze(module_request, [module])
        self.assertEqual(result["layers"]["protocol"]["result"], "CONDITIONALLY_COMPATIBLE")

    def test_ac56_generic_ethernet_request_ignores_protocol_coverage(self):
        coverage = {"communication_protocols": {"complete": True}}
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c", catalog_coverage=coverage)
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c", catalog_coverage=coverage)
        result = self.analyze({"signal_family": "ethernet"}, source=source, target=target)
        self.assertEqual(result["result"], "COMPATIBLE")

    def test_real_nvx_with_complete_coverage_dante_is_incompatible(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze({"source": {"equipment_id": core["id"], "interface_id": "lan-a"}, "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"}, "requested_function": {"protocol_family": "dante"}, "analysis_scope": "CATALOG", "interconnect_assumption": "APPROPRIATE_MEDIUM"}, [core, nvx])
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_nvx_without_coverage_dante_is_unknown(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        nvx.pop("catalog_coverage", None)
        result = analyze({"source": {"equipment_id": core["id"], "interface_id": "lan-a"}, "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"}, "requested_function": {"protocol_family": "dante"}, "analysis_scope": "CATALOG", "interconnect_assumption": "APPROPRIATE_MEDIUM"}, [core, nvx])
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_real_nvx_complete_aes67_ethernet_one_is_conditional(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        nvx["catalog_coverage"] = {"communication_protocols": {"complete": True}}
        result = analyze({"source": {"equipment_id": core["id"], "interface_id": "lan-a"}, "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"}, "requested_function": {"protocol_family": "aes67"}, "analysis_scope": "CATALOG", "interconnect_assumption": "APPROPRIATE_MEDIUM"}, [core, nvx])
        self.assertEqual(result["result"], "CONDITIONALLY_COMPATIBLE")

    def test_real_core_complete_dm_nvx_is_incompatible(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        core["catalog_coverage"] = {"communication_protocols": {"complete": True}}
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze({"source": {"equipment_id": core["id"], "interface_id": "lan-a"}, "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"}, "requested_function": {"protocol_family": "dm-nvx"}, "analysis_scope": "CATALOG", "interconnect_assumption": "APPROPRIATE_MEDIUM"}, [core, nvx])
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_real_core_clone_without_coverage_dm_nvx_is_unknown(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        core.pop("catalog_coverage", None)
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze({"source": {"equipment_id": core["id"], "interface_id": "lan-a"}, "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"}, "requested_function": {"protocol_family": "dm-nvx"}, "analysis_scope": "CATALOG", "interconnect_assumption": "APPROPRIATE_MEDIUM"}, [core, nvx])
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac26_protocol_absent_on_source(self):
        source = equipment("source", signal=signal())
        target = equipment("target", signal=signal(protocol_family="rs-232"))
        result = self.analyze({"protocol_family": "rs-232"}, source=source, target=target)
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac27_protocol_absent_on_target(self):
        source = equipment("source", signal=signal(protocol_family="rs-232"))
        target = equipment("target", signal=signal())
        result = self.analyze({"protocol_family": "rs-232"}, source=source, target=target)
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac28_protocol_absent_on_both(self):
        result = self.analyze({"protocol_family": "rs-232"})
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac29_fixed_capability_allowed_on_interface(self):
        capability = {"id": "rs232-cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        records = [equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability]), equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])]
        result = analyze(request({"protocol_family": "rs-232"}), records)
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")

    def test_ac30_fixed_capability_bound_to_another_interface(self):
        capability = {"id": "rs232-cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["b"]}}
        source = equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])
        target = equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface={"id": "b", "label": "b"})
        target["interfaces"].append({"id": "a", "label": "a", "direction": "bidirectional", "connector": "hdmi-type-a", "connector_gender": "female", "signals": [signal(protocol_family="rs-232")]})
        result = self.analyze({"protocol_family": "rs-232"}, source=source, target=target)
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_ac31_configurable_capability_allowed_on_interface(self):
        capability = {"id": "rs232-cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "configurable", "allowed_interface_ids": ["a"]}}
        records = [equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability]), equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])]
        result = analyze(request({"protocol_family": "rs-232"}), records)
        self.assertEqual(result["result"], "CONDITIONALLY_COMPATIBLE")

    def test_ac32_configurable_capability_excludes_interface(self):
        capability = {"id": "rs232-cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "configurable", "allowed_interface_ids": ["b"]}}
        source = equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])
        target = equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface={"id": "b", "label": "b"})
        target["interfaces"].append({"id": "a", "label": "a", "direction": "bidirectional", "connector": "hdmi-type-a", "connector_gender": "female", "signals": [signal(protocol_family="rs-232")]})
        result = self.analyze({"protocol_family": "rs-232"}, source=source, target=target)
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_ac33_unavailable_protocol(self):
        capability = {"id": "rs232-cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "availability": "unavailable", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        records = [equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability]), equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])]
        self.assertEqual(analyze(request({"protocol_family": "rs-232"}), records)["result"], "INCOMPATIBLE")

    def test_ac34_conditional_protocol_availability(self):
        capability = {"id": "rs232-cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "availability": "conditional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        records = [equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability]), equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])]
        self.assertEqual(analyze(request({"protocol_family": "rs-232"}), records)["result"], "CONDITIONALLY_COMPATIBLE")

    def test_ac35_global_capability_excludes_requested_endpoint(self):
        capability = {"id": "rs232-cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["b"]}}
        source = equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])
        target = equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface={"id": "b", "label": "b"})
        target["interfaces"].append({"id": "a", "label": "a", "direction": "bidirectional", "connector": "hdmi-type-a", "connector_gender": "female", "signals": [signal(protocol_family="rs-232")]})
        self.assertEqual(self.analyze({"protocol_family": "rs-232"}, source=source, target=target)["result"], "INCOMPATIBLE")

    def test_ac36_rj45_ethernet_does_not_imply_protocol(self):
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c")
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c")
        result = self.analyze({"protocol_family": "aes67"}, source=source, target=target)
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")


if __name__ == "__main__":
    unittest.main()
