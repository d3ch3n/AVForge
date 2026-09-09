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


def request(function, assumption="APPROPRIATE_MEDIUM", source_id="source", target_id="target", electrical_requirements=None):
    value = {
        "source": {"equipment_id": source_id, "interface_id": "a"},
        "target": {"equipment_id": target_id, "interface_id": "a"},
        "requested_function": function,
        "analysis_scope": "CATALOG",
        "interconnect_assumption": assumption,
    }
    if electrical_requirements is not None:
        value["electrical_requirements"] = electrical_requirements
    return value


def passive_supported():
    return {"physical_connection_capabilities": {"passive_interconnection": {"status": "supported"}}}


def passive_unsupported():
    return {"physical_connection_capabilities": {"passive_interconnection": {"status": "unsupported"}}}


def analog_signal(direction="bidirectional"):
    return signal(signal_type="audio", signal_family="analog-audio", direction=direction)


def ec_output(modes=("balanced",), levels=("line",), **extra):
    profile = {"balance_modes": list(modes), "operating_level_classes": list(levels)}
    profile.update(extra)
    return {"electrical_characteristics": {"output": profile}}


def ec_input(modes=("balanced",), levels=("line",), **extra):
    profile = {"balance_modes": list(modes), "operating_level_classes": list(levels)}
    profile.update(extra)
    return {"electrical_characteristics": {"input": profile}}


class CompatibilityAnalyzerTests(unittest.TestCase):
    def analyze(self, function, source=None, target=None, **kwargs):
        source = source or equipment("source", signal=signal())
        target = target or equipment("target", signal=signal())
        return analyze(request(function, **kwargs), [source, target])

    def test_ac01_explicit_compatible_signal(self):
        source = equipment("source", signal=signal(), interface=passive_supported())
        target = equipment("target", signal=signal(), interface=passive_supported())
        result = self.analyze({"signal_family": "hdmi"}, source=source, target=target)
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

    def test_configurable_role_metadata_does_not_make_direction_conditional(self):
        source = equipment(
            "source",
            signal=signal(direction="bidirectional", configurable_role="input or output"),
        )
        result = self.analyze({"signal_family": "hdmi"}, source=source)
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")

    def test_ac14_irrelevant_electrical_is_not_applicable(self):
        result = self.analyze({"protocol_family": "aes67"})
        self.assertFalse(result["layers"]["electrical"]["applicable"])

    def test_ac15_required_electrical_missing(self):
        source = equipment("source", signal=signal(signal_type="audio", signal_family="analog-audio", direction="output", balanced=True))
        target = equipment("target", signal=signal(signal_type="audio", signal_family="analog-audio", direction="input"))
        result = self.analyze({"signal_family": "analog-audio"}, source=source, target=target)
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_signal_selection_source_uses_output_signal_not_array_order(self):
        input_signal = signal(signal_type="audio", signal_family="analog-audio", direction="input")
        input_signal["id"] = "input"
        output_signal = signal(signal_type="audio", signal_family="analog-audio", direction="output", balanced=True)
        output_signal["id"] = "output"
        source = equipment("source", signal=None, interface={"signals": [input_signal, output_signal], "electrical_characteristics": {"output": {"balance_modes": ["balanced"], "operating_level_classes": ["line"]}}})
        target = equipment("target", signal=signal(signal_type="audio", signal_family="analog-audio", direction="input", balanced=True), interface=ec_input())
        result = self.analyze({"signal_family": "analog-audio"}, source=source, target=target)
        self.assertEqual(result["layers"]["electrical"]["result"], "COMPATIBLE")

        source["interfaces"][0]["signals"] = [output_signal, input_signal]
        reversed_result = self.analyze({"signal_family": "analog-audio"}, source=source, target=target)
        self.assertEqual(reversed_result["layers"]["electrical"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], reversed_result["result"])

    def test_signal_selection_target_uses_input_signal_not_array_order(self):
        output_signal = signal(signal_type="audio", signal_family="analog-audio", direction="output")
        output_signal["id"] = "output"
        input_signal = signal(signal_type="audio", signal_family="analog-audio", direction="input", balanced=True)
        input_signal["id"] = "input"
        target = equipment("target", signal=None, interface={"signals": [output_signal, input_signal], "electrical_characteristics": {"input": {"balance_modes": ["balanced"], "operating_level_classes": ["line"]}}})
        source = equipment("source", signal=signal(signal_type="audio", signal_family="analog-audio", direction="output", balanced=True), interface=ec_output())
        result = self.analyze({"signal_family": "analog-audio"}, source=source, target=target)
        self.assertEqual(result["layers"]["electrical"]["result"], "COMPATIBLE")

        target["interfaces"][0]["signals"] = [input_signal, output_signal]
        reversed_result = self.analyze({"signal_family": "analog-audio"}, source=source, target=target)
        self.assertEqual(reversed_result["layers"]["electrical"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], reversed_result["result"])

    def test_signal_selection_restricts_type_and_family_before_role(self):
        irrelevant = signal(signal_type="video", signal_family="hdmi", direction="output")
        irrelevant["id"] = "irrelevant"
        audio_input = signal(signal_type="audio", signal_family="analog-audio", direction="input")
        audio_input["id"] = "audio-input"
        audio_output = signal(signal_type="audio", signal_family="analog-audio", direction="output", balanced=True)
        audio_output["id"] = "audio-output"
        source = equipment("source", signal=None, interface={"signals": [irrelevant, audio_input, audio_output], "electrical_characteristics": {"output": {"balance_modes": ["balanced"], "operating_level_classes": ["line"]}}})
        target = equipment("target", signal=signal(signal_type="audio", signal_family="analog-audio", direction="input", balanced=True), interface=ec_input())
        result = self.analyze({"signal_type": "audio", "signal_family": "analog-audio"}, source=source, target=target)
        self.assertEqual(result["layers"]["electrical"]["result"], "COMPATIBLE")

        source["interfaces"][0]["signals"] = [audio_output, audio_input, irrelevant]
        reversed_result = self.analyze({"signal_type": "audio", "signal_family": "analog-audio"}, source=source, target=target)
        self.assertEqual(result["result"], reversed_result["result"])

    def test_signal_selection_accepts_bidirectional_signal_for_both_roles(self):
        bidirectional = signal(signal_type="audio", signal_family="analog-audio", direction="bidirectional", balanced=True)
        source = equipment("source", signal=bidirectional, interface=ec_output())
        target = equipment("target", signal=signal(signal_type="audio", signal_family="analog-audio", direction="input", balanced=True), interface=ec_input())
        source_result = self.analyze({"signal_family": "analog-audio"}, source=source, target=target)
        self.assertEqual(source_result["layers"]["electrical"]["result"], "COMPATIBLE")

        target_result = self.analyze({"signal_family": "analog-audio"}, source=equipment("source", signal=signal(signal_type="audio", signal_family="analog-audio", direction="output", balanced=True), interface=ec_output()), target=equipment("target", signal=bidirectional, interface=ec_input()))
        self.assertEqual(target_result["layers"]["electrical"]["result"], "COMPATIBLE")

    def test_signal_selection_does_not_choose_ambiguous_candidates(self):
        first_output = signal(signal_type="audio", signal_family="analog-audio", direction="output", balanced=True)
        first_output["id"] = "first-output"
        second_output = signal(signal_type="audio", signal_family="analog-audio", direction="output", balanced=True)
        second_output["id"] = "second-output"
        source = equipment("source", signal=None, interface={"signals": [first_output, second_output]})
        target = equipment("target", signal=signal(signal_type="audio", signal_family="analog-audio", direction="input", balanced=True))
        result = self.analyze({"signal_family": "analog-audio"}, source=source, target=target)
        self.assertEqual(result["layers"]["electrical"]["result"], "INSUFFICIENT_DATA")

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

    def test_ac23_electrical_insufficient_without_direction_condition(self):
        source = equipment("source", signal=signal(signal_type="audio", signal_family="analog-audio", direction="bidirectional", configurable_role="input or output"))
        target = equipment("target", signal=signal(signal_type="audio", signal_family="analog-audio", direction="bidirectional"))
        result = self.analyze({"signal_family": "analog-audio"}, source=source, target=target)
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")
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
        source = equipment("source", signal=signal(), interface=passive_supported())
        target = equipment("target", signal=signal(), interface=passive_supported())
        result = self.analyze({"signal_family": "hdmi"}, source=source, target=target, assumption="APPROPRIATE_MEDIUM")
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
        source = equipment("source", signal=signal(), catalog_coverage={"communication_protocols": {"complete": True}}, interface=passive_supported())
        target = equipment("target", signal=signal(), catalog_coverage={"communication_protocols": {"complete": True}}, interface=passive_supported())
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
        records = [equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface=passive_supported()), equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface=passive_supported())]
        self.assertEqual(analyze(request({"protocol_family": "rs-232"}), records)["result"], "CONDITIONALLY_COMPATIBLE")

    def test_ac49_complete_coverage_precedes_other_compatible_layers(self):
        coverage = {"communication_protocols": {"complete": True}}
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c", catalog_coverage=coverage, interface=passive_supported())
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c", catalog_coverage=coverage, interface=passive_supported())
        result = self.analyze({"protocol_family": "dante"}, source=source, target=target)
        self.assertEqual(result["layers"]["physical"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_ac50_incomplete_coverage_keeps_unknown_result(self):
        coverage = {"communication_protocols": {"complete": False}}
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c", catalog_coverage=coverage, interface=passive_supported())
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c", catalog_coverage=coverage, interface=passive_supported())
        result = self.analyze({"protocol_family": "dante"}, source=source, target=target)
        self.assertEqual(result["layers"]["physical"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_ac51_protocol_coverage_does_not_change_electrical_layer(self):
        coverage = {"communication_protocols": {"complete": True}}
        source = equipment("source", signal=signal(signal_type="audio", signal_family="analog-audio", direction="output", balanced=True), catalog_coverage=coverage, interface=ec_output())
        target = equipment("target", signal=signal(signal_type="audio", signal_family="analog-audio", direction="input", balanced=True), catalog_coverage=coverage, interface=ec_input())
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
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c", catalog_coverage=coverage, interface=passive_supported())
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c", catalog_coverage=coverage, interface=passive_supported())
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
        records = [equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface=passive_supported()), equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface=passive_supported())]
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
        records = [equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface=passive_supported()), equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface=passive_supported())]
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


class PhysicalConnectionModelV1Tests(unittest.TestCase):
    def physical(self, source, target, assumption="APPROPRIATE_MEDIUM"):
        result = analyze(
            {
                "source": {"equipment_id": "source", "interface_id": "a"},
                "target": {"equipment_id": "target", "interface_id": "a"},
                "requested_function": {"signal_family": "hdmi"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": assumption,
            },
            [source, target],
        )
        return result["layers"]["physical"]["result"]

    def test_p01_supported_supported_same_connector_is_compatible(self):
        source = equipment("source", signal=signal(), connector="hdmi-type-a", interface=passive_supported())
        target = equipment("target", signal=signal(), connector="hdmi-type-a", interface=passive_supported())
        self.assertEqual(self.physical(source, target), "COMPATIBLE")

    def test_p02_supported_supported_different_connectors_is_compatible(self):
        source = equipment("source", signal=signal(), connector="hdmi-type-a", interface=passive_supported())
        target = equipment("target", signal=signal(), connector="usb-type-c", interface=passive_supported())
        self.assertEqual(self.physical(source, target), "COMPATIBLE")

    def test_p03_supported_unknown_is_insufficient(self):
        source = equipment("source", signal=signal(), interface=passive_supported())
        target = equipment("target", signal=signal())
        self.assertEqual(self.physical(source, target), "INSUFFICIENT_DATA")

    def test_p04_unknown_supported_is_insufficient(self):
        source = equipment("source", signal=signal())
        target = equipment("target", signal=signal(), interface=passive_supported())
        self.assertEqual(self.physical(source, target), "INSUFFICIENT_DATA")

    def test_p05_unknown_unknown_is_insufficient(self):
        source = equipment("source", signal=signal())
        target = equipment("target", signal=signal())
        self.assertEqual(self.physical(source, target), "INSUFFICIENT_DATA")

    def test_p06_unsupported_supported_is_incompatible(self):
        source = equipment("source", signal=signal(), interface=passive_unsupported())
        target = equipment("target", signal=signal(), interface=passive_supported())
        self.assertEqual(self.physical(source, target), "INCOMPATIBLE")

    def test_p07_supported_unsupported_is_incompatible(self):
        source = equipment("source", signal=signal(), interface=passive_supported())
        target = equipment("target", signal=signal(), interface=passive_unsupported())
        self.assertEqual(self.physical(source, target), "INCOMPATIBLE")

    def test_p08_unsupported_unknown_is_incompatible(self):
        source = equipment("source", signal=signal(), interface=passive_unsupported())
        target = equipment("target", signal=signal())
        self.assertEqual(self.physical(source, target), "INCOMPATIBLE")

    def test_p09_unknown_unsupported_is_incompatible(self):
        source = equipment("source", signal=signal())
        target = equipment("target", signal=signal(), interface=passive_unsupported())
        self.assertEqual(self.physical(source, target), "INCOMPATIBLE")

    def test_p10_direct_ignores_passive_capability(self):
        source = equipment("source", signal=signal(), connector="hdmi-type-a", gender="female", interface=passive_supported())
        target = equipment("target", signal=signal(), connector="hdmi-type-a", gender="female", interface=passive_supported())
        self.assertEqual(self.physical(source, target, assumption="DIRECT"), "INCOMPATIBLE")
        unknown_source = equipment("source", signal=signal(), connector="hdmi-type-a", gender="male")
        unknown_target = equipment("target", signal=signal(), connector="hdmi-type-a", gender="female")
        self.assertEqual(self.physical(unknown_source, unknown_target, assumption="DIRECT"), "COMPATIBLE")

    def test_p11_appropriate_medium_does_not_require_connector_equality(self):
        source = equipment("source", signal=signal(), connector="hdmi-type-a", interface=passive_supported())
        target = equipment("target", signal=signal(), connector="rj45-8p8c", interface=passive_supported())
        self.assertEqual(self.physical(source, target), "COMPATIBLE")

    def test_p12_legacy_known_connector_without_capability_is_insufficient(self):
        source = equipment("source", signal=signal(), connector="hdmi-type-a")
        target = equipment("target", signal=signal(), connector="hdmi-type-a")
        self.assertEqual(self.physical(source, target), "INSUFFICIENT_DATA")

    def test_p13_different_terminal_blocks_supported_supported_is_compatible(self):
        source = equipment("source", signal=signal(), connector="pluggable-terminal-block", interface=passive_supported())
        target = equipment("target", signal=signal(), connector="terminal-block-5-pin-3-5mm", interface=passive_supported())
        self.assertEqual(self.physical(source, target), "COMPATIBLE")

    def test_p14_physical_compatible_signal_incompatible_stays_incompatible(self):
        source = equipment("source", signal=signal(signal_family="hdmi"), interface=passive_supported())
        target = equipment("target", signal=signal(signal_family="analog-audio"), interface=passive_supported())
        result = analyze(
            {
                "source": {"equipment_id": "source", "interface_id": "a"},
                "target": {"equipment_id": "target", "interface_id": "a"},
                "requested_function": {"signal_family": "hdmi"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [source, target],
        )
        self.assertEqual(result["layers"]["physical"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_p15_service_console_without_capability_is_insufficient(self):
        chassis = load_record("equipment/crestron/dmf-ci-8.json")
        module = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze(
            {
                "source": {"equipment_id": chassis["id"], "interface_id": "console-serial"},
                "target": {"equipment_id": module["id"], "interface_id": "ethernet-1"},
                "requested_function": {"signal_family": "ethernet"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [chassis, module],
        )
        self.assertEqual(result["layers"]["physical"]["result"], "INSUFFICIENT_DATA")


class ElectricalAnalyzerV1Tests(unittest.TestCase):
    def electrical(self, source, target, function=None, electrical_requirements=None, **kwargs):
        request_function = {"signal_family": "analog-audio"}
        request_function.update(function or {})
        return analyze(
            request(request_function, electrical_requirements=electrical_requirements, **kwargs),
            [source, target],
        )["layers"]["electrical"]

    def analog_pair(self, source_profile, target_profile, source_direction="output", target_direction="input"):
        source = equipment(
            "source",
            signal=signal(signal_type="audio", signal_family="analog-audio", direction=source_direction),
            interface={"electrical_characteristics": {"output": source_profile}} if source_profile is not None else {},
        )
        target = equipment(
            "target",
            signal=signal(signal_type="audio", signal_family="analog-audio", direction=target_direction),
            interface={"electrical_characteristics": {"input": target_profile}} if target_profile is not None else {},
        )
        return source, target

    def test_e01_balanced_supported_both(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
        )
        self.assertEqual(self.electrical(source, target)["result"], "COMPATIBLE")

    def test_e02_unbalanced_supported_both(self):
        source, target = self.analog_pair(
            {"balance_modes": ["unbalanced"], "operating_level_classes": ["line"]},
            {"balance_modes": ["unbalanced"], "operating_level_classes": ["line"]},
        )
        self.assertEqual(self.electrical(source, target)["result"], "COMPATIBLE")

    def test_e03_requested_balanced_unsupported_source(self):
        source, target = self.analog_pair(
            {"balance_modes": ["unbalanced"], "operating_level_classes": ["line"]},
            {"balance_modes": ["balanced", "unbalanced"], "operating_level_classes": ["line"]},
        )
        layer = self.electrical(source, target, electrical_requirements={"balance_mode": "balanced"})
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_e04_requested_balanced_unsupported_target(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced", "unbalanced"], "operating_level_classes": ["line"]},
            {"balance_modes": ["unbalanced"], "operating_level_classes": ["line"]},
        )
        layer = self.electrical(source, target, electrical_requirements={"balance_mode": "balanced"})
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_e05_requested_mode_missing_source_info(self):
        source, target = self.analog_pair(
            {"operating_level_classes": ["line"]},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
        )
        layer = self.electrical(source, target, electrical_requirements={"balance_mode": "balanced"})
        self.assertEqual(layer["result"], "INSUFFICIENT_DATA")

    def test_e06_requested_mode_missing_target_info(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
            {"operating_level_classes": ["line"]},
        )
        layer = self.electrical(source, target, electrical_requirements={"balance_mode": "balanced"})
        self.assertEqual(layer["result"], "INSUFFICIENT_DATA")

    def test_e07_multiple_modes_one_compatible(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced", "unbalanced"], "operating_level_classes": ["line"]},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
        )
        self.assertEqual(self.electrical(source, target)["result"], "COMPATIBLE")

    def test_e08_balanced_variant_resolved(self):
        source, target = self.analog_pair(
            {
                "balance_modes": ["balanced", "unbalanced"],
                "operating_level_classes": ["line"],
                "variants": [
                    {"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}},
                    {"conditions": {"balance_mode": "unbalanced"}, "maximum_level": {"value": 2, "unit": "volt-rms"}},
                ],
            },
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
        )
        layer = self.electrical(source, target, electrical_requirements={"balance_mode": "balanced"})
        self.assertEqual(layer["result"], "COMPATIBLE")
        self.assertTrue(any("4" in reason for reason in layer["reasons"]))

    def test_e09_unbalanced_variant_resolved(self):
        source, target = self.analog_pair(
            {
                "balance_modes": ["balanced", "unbalanced"],
                "operating_level_classes": ["line"],
                "variants": [
                    {"conditions": {"balance_mode": "balanced"}, "impedance": {"nominal": {"value": 200, "unit": "ohm"}}},
                    {"conditions": {"balance_mode": "unbalanced"}, "impedance": {"nominal": {"value": 100, "unit": "ohm"}}},
                ],
            },
            {"balance_modes": ["unbalanced"], "operating_level_classes": ["line"]},
        )
        layer = self.electrical(source, target, electrical_requirements={"balance_mode": "unbalanced"})
        self.assertEqual(layer["result"], "COMPATIBLE")
        self.assertTrue(any("100" in reason or "Impedance" in reason for reason in layer["reasons"]))

    def test_e08b_duplicate_matching_variant_is_insufficient(self):
        source, target = self.analog_pair(
            {
                "balance_modes": ["balanced"],
                "operating_level_classes": ["line"],
                "maximum_level": {"value": 1, "unit": "volt-rms"},
                "variants": [
                    {"conditions": {"balance_mode": "balanced"}, "maximum_level": {"value": 4, "unit": "volt-rms"}},
                ],
            },
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
        )
        layer = self.electrical(source, target, electrical_requirements={"balance_mode": "balanced"})
        self.assertEqual(layer["result"], "INSUFFICIENT_DATA")

    def test_e10_line_output_to_line_input(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
        )
        self.assertEqual(self.electrical(source, target)["result"], "COMPATIBLE")

    def test_e11_line_output_to_mic_line_input(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
            {"balance_modes": ["balanced"], "operating_level_classes": ["mic", "line"]},
        )
        layer = self.electrical(source, target)
        self.assertEqual(layer["result"], "COMPATIBLE")
        self.assertTrue(any("line" in reason for reason in layer["reasons"]))

    def test_e12_line_output_to_mic_only_input(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
            {"balance_modes": ["balanced"], "operating_level_classes": ["mic"]},
        )
        self.assertEqual(self.electrical(source, target)["result"], "INCOMPATIBLE")

    def test_e12b_missing_operating_level_is_insufficient(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"]},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
        )
        self.assertEqual(self.electrical(source, target)["result"], "INSUFFICIENT_DATA")
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
            {"balance_modes": ["balanced"]},
        )
        self.assertEqual(self.electrical(source, target)["result"], "INSUFFICIENT_DATA")

    def test_e13_maximum_level_is_informational(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "maximum_level": {"value": 10, "unit": "volt-rms"}},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "maximum_level": {"value": 2, "unit": "volt-rms"}},
        )
        self.assertEqual(self.electrical(source, target)["result"], "COMPATIBLE")

    def test_e14_nominal_levels_are_informational(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "nominal_levels": [{"value": 4, "unit": "decibel-u"}]},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "nominal_levels": [{"value": -10, "unit": "decibel-u"}]},
        )
        self.assertEqual(self.electrical(source, target)["result"], "COMPATIBLE")

    def test_e15_ordinary_impedance_is_informational(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "impedance": {"nominal": {"value": 100, "unit": "ohm"}}},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "impedance": {"nominal": {"value": 24000, "unit": "ohm"}}},
        )
        self.assertEqual(self.electrical(source, target)["result"], "COMPATIBLE")

    def test_e16_minimum_load_satisfied(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "minimum_load_impedance": {"value": 600, "unit": "ohm"}},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "impedance": {"nominal": {"value": 24000, "unit": "ohm"}}},
        )
        self.assertEqual(self.electrical(source, target)["result"], "COMPATIBLE")

    def test_e17_minimum_load_violated(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "minimum_load_impedance": {"value": 600, "unit": "ohm"}},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "impedance": {"nominal": {"value": 100, "unit": "ohm"}}},
        )
        self.assertEqual(self.electrical(source, target)["result"], "INCOMPATIBLE")

    def test_e18_minimum_load_target_unknown(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "minimum_load_impedance": {"value": 600, "unit": "ohm"}},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
        )
        self.assertEqual(self.electrical(source, target)["result"], "INSUFFICIENT_DATA")

    def test_e18b_minimum_load_unit_mismatch_or_upper_bound_only(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "minimum_load_impedance": {"value": 600, "unit": "ohm"}},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "impedance": {"nominal": {"value": 1, "unit": "kilohm"}}},
        )
        self.assertEqual(self.electrical(source, target)["result"], "INSUFFICIENT_DATA")
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "minimum_load_impedance": {"value": 600, "unit": "ohm"}},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"], "impedance": {"upper_bound": {"value": 100, "unit": "ohm", "inclusive": False}}},
        )
        self.assertEqual(self.electrical(source, target)["result"], "INSUFFICIENT_DATA")

    def test_e19_physical_compatible_electrical_incompatible_is_incompatible(self):
        source = equipment(
            "source",
            signal=signal(signal_type="audio", signal_family="analog-audio", direction="output"),
            interface={**passive_supported(), "electrical_characteristics": {"output": {"balance_modes": ["balanced"], "operating_level_classes": ["line"]}}},
        )
        target = equipment(
            "target",
            signal=signal(signal_type="audio", signal_family="analog-audio", direction="input"),
            interface={**passive_supported(), "electrical_characteristics": {"input": {"balance_modes": ["balanced"], "operating_level_classes": ["mic"]}}},
        )
        result = analyze(request({"signal_family": "analog-audio"}), [source, target])
        self.assertEqual(result["layers"]["physical"]["result"], "COMPATIBLE")
        self.assertEqual(result["layers"]["electrical"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_e20_electrical_unknown_yields_final_insufficient(self):
        source = equipment(
            "source",
            signal=signal(signal_type="audio", signal_family="analog-audio", direction="output"),
            interface=passive_supported(),
        )
        target = equipment(
            "target",
            signal=signal(signal_type="audio", signal_family="analog-audio", direction="input"),
            interface=passive_supported(),
        )
        result = analyze(request({"signal_family": "analog-audio"}), [source, target])
        self.assertEqual(result["layers"]["electrical"]["result"], "INSUFFICIENT_DATA")
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_e21_digital_case_not_applicable(self):
        result = analyze(request({"signal_family": "hdmi"}), [equipment("source"), equipment("target")])
        self.assertFalse(result["layers"]["electrical"]["applicable"])

    def test_e22_legacy_balanced_without_canonical_is_insufficient(self):
        source = equipment("source", signal=signal(signal_type="audio", signal_family="analog-audio", direction="output", balanced=True))
        target = equipment("target", signal=signal(signal_type="audio", signal_family="analog-audio", direction="input", balanced=True))
        result = analyze(request({"signal_family": "analog-audio"}), [source, target])
        self.assertEqual(result["layers"]["electrical"]["result"], "INSUFFICIENT_DATA")

    def test_e23_request_validation(self):
        source = equipment(
            "source",
            signal=signal(signal_type="audio", signal_family="analog-audio", direction="output"),
            interface=ec_output(),
        )
        target = equipment(
            "target",
            signal=signal(signal_type="audio", signal_family="analog-audio", direction="input"),
            interface=ec_input(),
        )
        valid = analyze(request({"signal_family": "analog-audio"}, electrical_requirements={"balance_mode": "balanced"}), [source, target])
        self.assertEqual(valid["layers"]["electrical"]["result"], "COMPATIBLE")
        valid_unbalanced = analyze(request({"signal_family": "analog-audio"}, electrical_requirements={"balance_mode": "unbalanced"}), [source, target])
        self.assertEqual(valid_unbalanced["layers"]["electrical"]["result"], "INCOMPATIBLE")
        with self.assertRaises(AnalysisInputError):
            analyze(request({"signal_family": "analog-audio"}, electrical_requirements={"balance_mode": "foo"}), [source, target])
        with self.assertRaises(AnalysisInputError):
            analyze(request({"signal_family": "analog-audio"}, electrical_requirements="balanced"), [source, target])
        empty_requirements = analyze(request({"signal_family": "analog-audio"}, electrical_requirements={}), [source, target])
        self.assertEqual(empty_requirements["layers"]["electrical"]["result"], "COMPATIBLE")
        no_requirements = analyze(request({"signal_family": "analog-audio"}), [source, target])
        self.assertEqual(no_requirements["layers"]["electrical"]["result"], "COMPATIBLE")

    def test_e27_nested_electrical_requirements_is_not_consumed(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced", "unbalanced"], "operating_level_classes": ["line"]},
            {"balance_modes": ["balanced", "unbalanced"], "operating_level_classes": ["line"]},
        )
        nested_only = analyze(
            request({"signal_family": "analog-audio", "electrical_requirements": {"balance_mode": "balanced"}}),
            [source, target],
        )
        root_only = analyze(
            request({"signal_family": "analog-audio"}, electrical_requirements={"balance_mode": "balanced"}),
            [source, target],
        )
        self.assertEqual(root_only["layers"]["electrical"]["result"], "COMPATIBLE")
        self.assertEqual(
            root_only["layers"]["electrical"]["reasons"],
            ["Balance mode balanced is supported by both endpoints with operating level overlap ['line']."],
        )
        self.assertIn("Compatible balance mode(s): ['balanced', 'unbalanced'].", nested_only["layers"]["electrical"]["reasons"])

    def test_e28_root_and_nested_conflict_root_governs(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
            {"balance_modes": ["balanced"], "operating_level_classes": ["line"]},
        )
        result = analyze(
            request(
                {"signal_family": "analog-audio", "electrical_requirements": {"balance_mode": "unbalanced"}},
                electrical_requirements={"balance_mode": "balanced"},
            ),
            [source, target],
        )
        self.assertEqual(result["layers"]["electrical"]["result"], "COMPATIBLE")

    def test_e24_no_conditional_for_mode_choice(self):
        source, target = self.analog_pair(
            {"balance_modes": ["balanced", "unbalanced"], "operating_level_classes": ["line"]},
            {"balance_modes": ["balanced", "unbalanced"], "operating_level_classes": ["line"]},
        )
        layer = self.electrical(source, target)
        self.assertEqual(layer["result"], "COMPATIBLE")
        self.assertNotEqual(layer["result"], "CONDITIONALLY_COMPATIBLE")

    def test_e25_real_analog_cases_are_electrically_compatible(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        hd = load_record("equipment/crestron/hd-md8x8-4kz-e.json")
        cases = [
            (core, "flex-1", nvx, "audio-io"),
            (nvx, "audio-io", core, "flex-1"),
            (hd, "audio-out-aux-1", nvx, "audio-io"),
            (hd, "audio-out-aux-1", core, "flex-1"),
        ]
        for source_record, source_interface, target_record, target_interface in cases:
            with self.subTest(source=source_interface, target=target_interface):
                result = analyze(
                    {
                        "source": {"equipment_id": source_record["id"], "interface_id": source_interface},
                        "target": {"equipment_id": target_record["id"], "interface_id": target_interface},
                        "requested_function": {"signal_family": "analog-audio"},
                        "analysis_scope": "CATALOG",
                        "interconnect_assumption": "APPROPRIATE_MEDIUM",
                    },
                    [core, nvx, hd],
                )
                self.assertEqual(result["layers"]["electrical"]["result"], "COMPATIBLE")

    def test_e26_real_variant_evidence_resolves(self):
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        audio = next(interface for interface in nvx["interfaces"] if interface["id"] == "audio-io")
        output = audio["electrical_characteristics"]["output"]
        balanced = next(variant for variant in output["variants"] if variant["conditions"]["balance_mode"] == "balanced")
        unbalanced = next(variant for variant in output["variants"] if variant["conditions"]["balance_mode"] == "unbalanced")
        self.assertEqual(balanced["impedance"]["nominal"]["value"], 200)
        self.assertEqual(unbalanced["impedance"]["nominal"]["value"], 100)
        self.assertEqual(balanced["maximum_level"]["value"], 4)
        self.assertEqual(unbalanced["maximum_level"]["value"], 2)


    def test_e26_real_variant_evidence_resolves(self):
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        audio = next(interface for interface in nvx["interfaces"] if interface["id"] == "audio-io")
        output = audio["electrical_characteristics"]["output"]
        balanced = next(variant for variant in output["variants"] if variant["conditions"]["balance_mode"] == "balanced")
        unbalanced = next(variant for variant in output["variants"] if variant["conditions"]["balance_mode"] == "unbalanced")
        self.assertEqual(balanced["impedance"]["nominal"]["value"], 200)
        self.assertEqual(unbalanced["impedance"]["nominal"]["value"], 100)
        self.assertEqual(balanced["maximum_level"]["value"], 4)
        self.assertEqual(unbalanced["maximum_level"]["value"], 2)


class DirectionLayerV1Tests(unittest.TestCase):
    def direction(self, source, target, function=None, **kwargs):
        request_function = {"signal_family": "hdmi"}
        request_function.update(function or {})
        return analyze(
            request(request_function, **kwargs),
            [source, target],
        )["layers"]["direction"]

    def video_pair(self, source_direction, target_direction, source_extra=None, target_extra=None):
        source_signal = {"id": "signal", "name": "signal", "signal_type": "video", "signal_family": "hdmi"}
        if source_direction is not None:
            source_signal["direction"] = source_direction
        if source_extra:
            source_signal.update(source_extra)
        target_signal = {"id": "signal", "name": "signal", "signal_type": "video", "signal_family": "hdmi"}
        if target_direction is not None:
            target_signal["direction"] = target_direction
        if target_extra:
            target_signal.update(target_extra)
        source = equipment("source", signal=None, interface={"signals": [source_signal]})
        target = equipment("target", signal=None, interface={"signals": [target_signal]})
        return source, target

    def test_d01_output_to_input_is_compatible(self):
        source, target = self.video_pair("output", "input")
        self.assertEqual(self.direction(source, target)["result"], "COMPATIBLE")

    def test_d02_bidirectional_source_to_input_is_compatible(self):
        source, target = self.video_pair("bidirectional", "input")
        self.assertEqual(self.direction(source, target)["result"], "COMPATIBLE")

    def test_d03_output_to_bidirectional_target_is_compatible(self):
        source, target = self.video_pair("output", "bidirectional")
        self.assertEqual(self.direction(source, target)["result"], "COMPATIBLE")

    def test_d04_bidirectional_to_bidirectional_is_compatible(self):
        source, target = self.video_pair("bidirectional", "bidirectional")
        self.assertEqual(self.direction(source, target)["result"], "COMPATIBLE")

    def test_d05_input_only_source_is_incompatible(self):
        source, target = self.video_pair("input", "input")
        self.assertEqual(self.direction(source, target)["result"], "INCOMPATIBLE")

    def test_d06_output_only_target_is_incompatible(self):
        source, target = self.video_pair("output", "output")
        self.assertEqual(self.direction(source, target)["result"], "INCOMPATIBLE")

    def test_d07_missing_source_direction_is_insufficient(self):
        source, target = self.video_pair(None, "input")
        self.assertEqual(self.direction(source, target)["result"], "INSUFFICIENT_DATA")

    def test_d08_missing_target_direction_is_insufficient(self):
        source, target = self.video_pair("output", None)
        self.assertEqual(self.direction(source, target)["result"], "INSUFFICIENT_DATA")

    def test_d09_configurable_role_does_not_change_compatible_direction(self):
        source, target = self.video_pair(
            "output", "input",
            source_extra={"signal_characteristics": {"configurable_role": "output"}},
        )
        self.assertEqual(self.direction(source, target)["result"], "COMPATIBLE")
        legacy_source, legacy_target = self.video_pair(
            "bidirectional", "bidirectional",
            source_extra={"signal_characteristics": {"configurable_role": "input or output, not both"}},
        )
        self.assertEqual(self.direction(legacy_source, legacy_target)["result"], "COMPATIBLE")

    def test_d11_absent_configurable_role_is_compatible(self):
        source, target = self.video_pair("output", "input")
        self.assertEqual(self.direction(source, target)["result"], "COMPATIBLE")

    def test_d12_ambiguous_candidates_remain_insufficient(self):
        first = {"id": "first", "name": "first", "signal_type": "video", "signal_family": "hdmi", "direction": "output"}
        second = {"id": "second", "name": "second", "signal_type": "video", "signal_family": "hdmi", "direction": "output"}
        source = equipment("source", signal=None, interface={"signals": [first, second]})
        target = equipment("target", signal=signal(direction="input"))
        result = analyze(request({"signal_family": "hdmi"}), [source, target])
        self.assertEqual(result["layers"]["direction"]["result"], "INSUFFICIENT_DATA")

    def test_d13_direction_incompatible_makes_final_incompatible(self):
        source = equipment(
            "source",
            signal=signal(signal_type="audio", signal_family="analog-audio", direction="output"),
            interface={
                **passive_supported(),
                "electrical_characteristics": {"output": {"balance_modes": ["balanced"], "operating_level_classes": ["line"]}},
            },
        )
        target = equipment(
            "target",
            signal=signal(signal_type="audio", signal_family="analog-audio", direction="input"),
            interface={
                **passive_supported(),
                "electrical_characteristics": {"input": {"balance_modes": ["balanced"], "operating_level_classes": ["line"]}},
            },
        )
        compatible = analyze(request({"signal_family": "analog-audio"}), [source, target])
        self.assertEqual(compatible["layers"]["direction"]["result"], "COMPATIBLE")
        self.assertEqual(compatible["result"], "COMPATIBLE")
        contradicted = analyze(request({"signal_family": "analog-audio", "direction": "input"}), [source, target])
        self.assertEqual(contradicted["layers"]["physical"]["result"], "COMPATIBLE")
        self.assertEqual(contradicted["layers"]["electrical"]["result"], "COMPATIBLE")
        self.assertEqual(contradicted["layers"]["direction"]["result"], "INCOMPATIBLE")
        self.assertEqual(contradicted["result"], "INCOMPATIBLE")

    def test_d14_four_real_analog_cases_are_compatible(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        hd = load_record("equipment/crestron/hd-md8x8-4kz-e.json")
        cases = [
            (core, "flex-1", nvx, "audio-io"),
            (nvx, "audio-io", core, "flex-1"),
            (hd, "audio-out-aux-1", nvx, "audio-io"),
            (hd, "audio-out-aux-1", core, "flex-1"),
        ]
        for source_record, source_interface, target_record, target_interface in cases:
            with self.subTest(source=source_interface, target=target_interface):
                result = analyze(
                    {
                        "source": {"equipment_id": source_record["id"], "interface_id": source_interface},
                        "target": {"equipment_id": target_record["id"], "interface_id": target_interface},
                        "requested_function": {"signal_family": "analog-audio"},
                        "analysis_scope": "CATALOG",
                        "interconnect_assumption": "APPROPRIATE_MEDIUM",
                    },
                    [core, nvx, hd],
                )
                self.assertEqual(result["layers"]["physical"]["result"], "COMPATIBLE")
                self.assertEqual(result["layers"]["electrical"]["result"], "COMPATIBLE")
                self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")
                self.assertEqual(result["result"], "COMPATIBLE")

    def test_d15_hdmi_output_to_input_is_compatible(self):
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        hd = load_record("equipment/crestron/hd-md8x8-4kz-e.json")
        result = analyze(
            {
                "source": {"equipment_id": nvx["id"], "interface_id": "hdmi-output"},
                "target": {"equipment_id": hd["id"], "interface_id": "hdmi-in-1"},
                "requested_function": {"signal_family": "hdmi"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [nvx, hd],
        )
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "COMPATIBLE")

    def test_d16_ethernet_bidirectional_is_compatible(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"},
                "requested_function": {"signal_family": "ethernet"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "COMPATIBLE")

    def test_d17_usb_bidirectional_is_compatible(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "usb-a-1"},
                "target": {"equipment_id": nvx["id"], "interface_id": "usb-host"},
                "requested_function": {"signal_type": "data"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")


if __name__ == "__main__":
    unittest.main()
