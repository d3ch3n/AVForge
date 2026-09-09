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
        result = analyze(request({"protocol_family": "rs-232"}), records)
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "COMPATIBLE")

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
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")

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

    def test_real_nvx_complete_aes67_ethernet_one_is_compatible(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        nvx["catalog_coverage"] = {"communication_protocols": {"complete": True}}
        result = analyze({"source": {"equipment_id": core["id"], "interface_id": "lan-a"}, "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"}, "requested_function": {"protocol_family": "aes67"}, "analysis_scope": "CATALOG", "interconnect_assumption": "APPROPRIATE_MEDIUM"}, [core, nvx])
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "COMPATIBLE")

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
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "COMPATIBLE")

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


class SignalLayerV1Tests(unittest.TestCase):
    def check_signal(self, source_signals, target_signals, function, assumption="APPROPRIATE_MEDIUM"):
        source = equipment("source", signal=None, interface={"signals": source_signals})
        target = equipment("target", signal=None, interface={"signals": target_signals})
        result = analyze(request(function, assumption=assumption), [source, target])
        return result["layers"]["signal"]["result"], result["result"]

    def audio_signal(self, signal_type="audio", signal_family="analog-audio", direction="bidirectional", signal_format=None):
        value = {"id": "signal", "name": "signal", "signal_type": signal_type, "direction": direction}
        if signal_family is not None:
            value["signal_family"] = signal_family
        if signal_format is not None:
            value["signal_format"] = signal_format
        return value

    def test_s01_matching_type_is_compatible(self):
        layer, _ = self.check_signal(
            [self.audio_signal(signal_family=None)],
            [self.audio_signal(signal_family=None)],
            {"signal_type": "audio"},
        )
        self.assertEqual(layer, "COMPATIBLE")

    def test_s02_mismatched_type_is_incompatible(self):
        layer, _ = self.check_signal(
            [self.audio_signal(signal_type="audio", signal_family=None)],
            [self.audio_signal(signal_type="video", signal_family=None)],
            {"signal_type": "audio"},
        )
        self.assertEqual(layer, "INCOMPATIBLE")

    def test_s03_matching_family_is_compatible(self):
        layer, _ = self.check_signal(
            [self.audio_signal()],
            [self.audio_signal()],
            {"signal_family": "analog-audio"},
        )
        self.assertEqual(layer, "COMPATIBLE")

    def test_s04_mismatched_family_is_incompatible(self):
        layer, _ = self.check_signal(
            [self.audio_signal(signal_family="analog-audio")],
            [self.audio_signal(signal_family="hdmi")],
            {"signal_family": "analog-audio"},
        )
        self.assertEqual(layer, "INCOMPATIBLE")

    def test_s05_type_and_family_both_match(self):
        layer, _ = self.check_signal(
            [self.audio_signal()],
            [self.audio_signal()],
            {"signal_type": "audio", "signal_family": "analog-audio"},
        )
        self.assertEqual(layer, "COMPATIBLE")

    def test_s06_type_match_family_mismatch(self):
        layer, _ = self.check_signal(
            [self.audio_signal()],
            [self.audio_signal(signal_type="audio", signal_family="hdmi")],
            {"signal_type": "audio", "signal_family": "analog-audio"},
        )
        self.assertEqual(layer, "INCOMPATIBLE")

    def test_s07_family_match_type_mismatch(self):
        layer, _ = self.check_signal(
            [self.audio_signal()],
            [self.audio_signal(signal_type="video", signal_family="analog-audio")],
            {"signal_type": "audio", "signal_family": "analog-audio"},
        )
        self.assertEqual(layer, "INCOMPATIBLE")

    def test_s08_type_requested_without_usable_data(self):
        source = equipment("source", signal=None, interface={"signals": []})
        target = equipment("target", signal=None, interface={"signals": []})
        result = analyze(request({"signal_type": "audio"}), [source, target])
        self.assertEqual(result["layers"]["signal"]["result"], "INSUFFICIENT_DATA")

    def test_s09_family_requested_family_absent_is_insufficient(self):
        layer, _ = self.check_signal(
            [self.audio_signal(signal_family=None)],
            [self.audio_signal()],
            {"signal_family": "analog-audio"},
        )
        self.assertEqual(layer, "INSUFFICIENT_DATA")

    def test_s10_core_style_input_output_same_family(self):
        source_signals = [
            self.audio_signal(direction="input"),
            self.audio_signal(direction="output"),
        ]
        target_signals = [self.audio_signal(direction="bidirectional")]
        layer, _ = self.check_signal(source_signals, target_signals, {"signal_family": "analog-audio"})
        self.assertEqual(layer, "COMPATIBLE")

    def test_s11_capability_exists_without_functional_identity(self):
        first = self.audio_signal(direction="output")
        first["id"] = "first"
        second = self.audio_signal(direction="output")
        second["id"] = "second"
        source = equipment("source", signal=None, interface={"signals": [first, second]})
        target = equipment("target", signal=self.audio_signal(direction="input"))
        result = analyze(request({"signal_family": "analog-audio"}), [source, target])
        self.assertEqual(result["layers"]["signal"]["result"], "COMPATIBLE")

    def test_s12_no_array_order_selection(self):
        first = self.audio_signal(signal_type="video", signal_family="hdmi", direction="output")
        first["id"] = "first"
        second = self.audio_signal(direction="output")
        second["id"] = "second"
        source = equipment("source", signal=None, interface={"signals": [first, second]})
        target = equipment("target", signal=self.audio_signal(direction="input"))
        forward = analyze(request({"signal_type": "audio", "signal_family": "analog-audio"}), [source, target])
        source["interfaces"][0]["signals"] = [second, first]
        reversed_order = analyze(request({"signal_type": "audio", "signal_family": "analog-audio"}), [source, target])
        self.assertEqual(forward["layers"]["signal"]["result"], "COMPATIBLE")
        self.assertEqual(forward["result"], reversed_order["result"])

    def test_s13_requested_format_supported(self):
        layer, _ = self.check_signal(
            [self.audio_signal(signal_format="X")],
            [self.audio_signal(signal_format="X")],
            {"signal_type": "audio", "signal_family": "analog-audio", "signal_format": "X"},
        )
        self.assertEqual(layer, "COMPATIBLE")

    def test_s14_requested_format_explicitly_unsupported(self):
        layer, _ = self.check_signal(
            [self.audio_signal(signal_format="X")],
            [self.audio_signal(signal_format="Y")],
            {"signal_type": "audio", "signal_family": "analog-audio", "signal_format": "X"},
        )
        self.assertEqual(layer, "INCOMPATIBLE")

    def test_s15_requested_format_missing_is_insufficient(self):
        layer, _ = self.check_signal(
            [self.audio_signal()],
            [self.audio_signal()],
            {"signal_type": "audio", "signal_family": "analog-audio", "signal_format": "X"},
        )
        self.assertEqual(layer, "INSUFFICIENT_DATA")

    def test_s22_format_mixed_evidence_stays_unknown(self):
        known_other = self.audio_signal(signal_type="video", signal_family="hdmi", signal_format="Y")
        unknown_format = self.audio_signal(signal_type="video", signal_family="hdmi")
        layer, _ = self.check_signal(
            [unknown_format, known_other],
            [self.audio_signal(signal_type="video", signal_family="hdmi", signal_format="X")],
            {"signal_type": "video", "signal_family": "hdmi", "signal_format": "X"},
        )
        self.assertEqual(layer, "INSUFFICIENT_DATA")

    def test_s16_no_requested_format_ignores_missing_format(self):
        layer, final = self.check_signal(
            [self.audio_signal()],
            [self.audio_signal()],
            {"signal_type": "audio", "signal_family": "analog-audio"},
        )
        self.assertEqual(layer, "COMPATIBLE")

    def test_s16b_conjunctive_constraints_share_one_signal(self):
        mixed_a = self.audio_signal(signal_type="audio", signal_family="hdmi")
        mixed_b = self.audio_signal(signal_type="video", signal_family="analog-audio")
        layer, _ = self.check_signal(
            [mixed_a, mixed_b],
            [self.audio_signal()],
            {"signal_type": "audio", "signal_family": "analog-audio"},
        )
        self.assertEqual(layer, "INCOMPATIBLE")

    def test_s17_four_real_analog_cases(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        hd = load_record("equipment/crestron/hd-md8x8-4kz-e.json")
        for source_record, source_interface, target_record, target_interface in [
            (core, "flex-1", nvx, "audio-io"),
            (nvx, "audio-io", core, "flex-1"),
            (hd, "audio-out-aux-1", nvx, "audio-io"),
            (hd, "audio-out-aux-1", core, "flex-1"),
        ]:
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
                self.assertEqual(result["layers"]["signal"]["result"], "COMPATIBLE")
                self.assertEqual(result["result"], "COMPATIBLE")

    def test_s18_hdmi_proves_only_requested_type_family(self):
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
        self.assertEqual(result["layers"]["signal"]["result"], "COMPATIBLE")

    def test_s19_ethernet_signal_without_protocol_proof(self):
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
        self.assertEqual(result["layers"]["signal"]["result"], "COMPATIBLE")
        protocol_only = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"},
                "requested_function": {"protocol_family": "aes67"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertFalse(protocol_only["layers"]["signal"]["applicable"])

    def test_s20_usb_data_without_family(self):
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
        self.assertEqual(result["layers"]["signal"]["result"], "COMPATIBLE")

    def test_s21_ethernet_signal_does_not_prove_protocol(self):
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c")
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c")
        result = analyze(request({"protocol_family": "aes67"}), [source, target])
        self.assertFalse(result["layers"]["signal"]["applicable"])
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_s22_signal_compatible_direction_incompatible(self):
        source = equipment(
            "source",
            signal=signal(signal_type="video", signal_family="hdmi", direction="output"),
            interface=passive_supported(),
        )
        target = equipment(
            "target",
            signal=signal(signal_type="video", signal_family="hdmi", direction="output"),
            interface=passive_supported(),
        )
        result = analyze(request({"signal_family": "hdmi"}), [source, target])
        self.assertEqual(result["layers"]["signal"]["result"], "COMPATIBLE")
        self.assertEqual(result["layers"]["direction"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")


class SignalOpenWorldIntegrationTests(unittest.TestCase):
    def run_case(self, source_signals, target_signals, function):
        source = equipment("source", signal=None, interface={"signals": source_signals})
        target = equipment("target", signal=None, interface={"signals": target_signals})
        return analyze(request(function), [source, target])

    def open_audio(self, family="analog-audio", direction="output", signal_format=None):
        value = {"id": "s", "name": "s", "signal_type": "audio", "direction": direction}
        if family is not None:
            value["signal_family"] = family
        if signal_format is not None:
            value["signal_format"] = signal_format
        return value

    def open_video(self, family="hdmi", direction="output", signal_format=None):
        value = {"id": "s", "name": "s", "signal_type": "video", "direction": direction}
        if family is not None:
            value["signal_family"] = family
        if signal_format is not None:
            value["signal_format"] = signal_format
        return value

    def test_a_source_family_missing_stays_insufficient(self):
        result = self.run_case(
            [self.open_audio(family=None, direction="output")],
            [self.open_audio(direction="input")],
            {"signal_family": "analog-audio"},
        )
        self.assertEqual(result["layers"]["signal"]["result"], "INSUFFICIENT_DATA")
        self.assertNotEqual(result["layers"]["direction"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_b_target_family_missing_stays_insufficient(self):
        result = self.run_case(
            [self.open_audio(direction="output")],
            [self.open_audio(family=None, direction="input")],
            {"signal_family": "analog-audio"},
        )
        self.assertEqual(result["layers"]["signal"]["result"], "INSUFFICIENT_DATA")
        self.assertNotEqual(result["layers"]["direction"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_c_source_format_missing_stays_insufficient(self):
        function = {"signal_type": "video", "signal_family": "hdmi", "signal_format": "X"}
        result = self.run_case(
            [self.open_video(direction="output")],
            [self.open_video(direction="input", signal_format="X")],
            function,
        )
        self.assertEqual(result["layers"]["signal"]["result"], "INSUFFICIENT_DATA")
        self.assertNotEqual(result["layers"]["direction"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_d_target_format_missing_stays_insufficient(self):
        function = {"signal_type": "video", "signal_family": "hdmi", "signal_format": "X"}
        result = self.run_case(
            [self.open_video(direction="output", signal_format="X")],
            [self.open_video(direction="input")],
            function,
        )
        self.assertEqual(result["layers"]["signal"]["result"], "INSUFFICIENT_DATA")
        self.assertNotEqual(result["layers"]["direction"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_e_mixed_unknown_and_mismatch_with_direction(self):
        unknown_format = self.open_video(direction="output")
        known_other = self.open_video(direction="output", signal_format="Y")
        known_other["id"] = "other"
        function = {"signal_type": "video", "signal_family": "hdmi", "signal_format": "X"}
        result = self.run_case(
            [unknown_format, known_other],
            [self.open_video(direction="input", signal_format="X")],
            function,
        )
        self.assertEqual(result["layers"]["signal"]["result"], "INSUFFICIENT_DATA")
        self.assertNotEqual(result["layers"]["direction"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_f_explicit_format_contradiction_controls(self):
        function = {"signal_type": "video", "signal_family": "hdmi", "signal_format": "X"}
        result = self.run_case(
            [self.open_video(direction="output", signal_format="Y")],
            [self.open_video(direction="input", signal_format="X")],
            function,
        )
        self.assertEqual(result["layers"]["signal"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")


class ProtocolLayerV1Tests(unittest.TestCase):
    def protocol(self, source, target, protocol, **kwargs):
        return analyze(
            request({"protocol_family": protocol}, **kwargs),
            [source, target],
        )["layers"]["protocol"]["result"]

    def proto_pair(self, source_protocols, target_protocols):
        source_signals = [
            {"id": f"s{i}", "name": f"s{i}", "signal_type": "control", "direction": "bidirectional", "protocol_family": proto}
            for i, proto in enumerate(source_protocols)
        ]
        target_signals = [
            {"id": f"t{i}", "name": f"t{i}", "signal_type": "control", "direction": "bidirectional", "protocol_family": proto}
            for i, proto in enumerate(target_protocols)
        ]
        source = equipment("source", signal=None, interface={"signals": source_signals})
        target = equipment("target", signal=None, interface={"signals": target_signals})
        return source, target

    def test_p01_exact_bilateral_match(self):
        source, target = self.proto_pair(["rs-232"], ["rs-232"])
        self.assertEqual(self.protocol(source, target, "rs-232"), "COMPATIBLE")

    def test_p02_source_explicit_mismatch(self):
        source, target = self.proto_pair(["usb"], ["rs-232"])
        self.assertEqual(self.protocol(source, target, "rs-232"), "INCOMPATIBLE")

    def test_p03_target_explicit_mismatch(self):
        source, target = self.proto_pair(["rs-232"], ["usb"])
        self.assertEqual(self.protocol(source, target, "rs-232"), "INCOMPATIBLE")

    def test_p04_source_unknown(self):
        source = equipment("source", signal=signal())
        target = equipment("target", signal=signal(protocol_family="rs-232"))
        self.assertEqual(self.protocol(source, target, "rs-232"), "INSUFFICIENT_DATA")

    def test_p05_target_unknown(self):
        source = equipment("source", signal=signal(protocol_family="rs-232"))
        target = equipment("target", signal=signal())
        self.assertEqual(self.protocol(source, target, "rs-232"), "INSUFFICIENT_DATA")

    def test_p06_both_unknown(self):
        source = equipment("source", signal=signal())
        target = equipment("target", signal=signal())
        self.assertEqual(self.protocol(source, target, "rs-232"), "INSUFFICIENT_DATA")

    def test_p07_multiple_capabilities_one_match(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        other = {"id": "other", "type": "control", "protocol_family": "cec", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(), communication_capabilities=[other, capability])
        target = equipment("target", signal=signal(), communication_capabilities=[capability, other])
        self.assertEqual(self.protocol(source, target, "rs-232"), "COMPATIBLE")

    def test_p08_multiple_equivalent_routes(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])
        target = equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])
        self.assertEqual(self.protocol(source, target, "rs-232"), "COMPATIBLE")

    def test_p09_no_array_order_selection(self):
        first = {"id": "first", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        second = {"id": "second", "type": "control", "protocol_family": "cec", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(), communication_capabilities=[first, second])
        target = equipment("target", signal=signal(), communication_capabilities=[second, first])
        forward = analyze(request({"protocol_family": "rs-232"}), [source, target])
        source["communication_capabilities"] = [second, first]
        target["communication_capabilities"] = [first, second]
        reversed_order = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertEqual(forward["layers"]["protocol"]["result"], "COMPATIBLE")
        self.assertEqual(forward["result"], reversed_order["result"])

    def test_p10_ethernet_signal_does_not_prove_aes67(self):
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c")
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c")
        result = analyze(request({"protocol_family": "aes67"}), [source, target])
        self.assertEqual(result["layers"]["protocol"]["result"], "INSUFFICIENT_DATA")

    def test_p11_signal_and_capability_or_evidence(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability])
        target = equipment("target", signal=signal(protocol_family="cec"))
        self.assertEqual(self.protocol(source, target, "rs-232"), "INCOMPATIBLE")
        both = equipment("target", signal=signal(protocol_family="cec"), communication_capabilities=[capability])
        self.assertEqual(self.protocol(source, both, "rs-232"), "COMPATIBLE")

    def test_p12_configurable_assignment_is_compatible(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "configurable", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(), communication_capabilities=[capability])
        target = equipment("target", signal=signal(), communication_capabilities=[capability])
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")

    def test_p13_fixed_assignment(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(), communication_capabilities=[capability])
        target = equipment("target", signal=signal(), communication_capabilities=[capability])
        self.assertEqual(self.protocol(source, target, "rs-232"), "COMPATIBLE")

    def test_p14_capability_direction_boundary(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "output", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(), communication_capabilities=[capability])
        target = equipment("target", signal=signal(), communication_capabilities=[capability])
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")

    def test_p15_protocol_signal_independence(self):
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), interface=passive_supported())
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), interface=passive_supported())
        result = analyze(request({"signal_family": "ethernet"}), [source, target])
        self.assertFalse(result["layers"]["protocol"]["applicable"])
        self.assertEqual(result["result"], "COMPATIBLE")

    def test_p16_protocol_direction_independence(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "configurable", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(direction="output"), communication_capabilities=[capability])
        target = equipment("target", signal=signal(direction="input"), communication_capabilities=[capability])
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")

    def test_p17_proprietary_protocol_needs_restrictions_layer(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "dm-nvx", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(), communication_capabilities=[capability])
        target = equipment("target", signal=signal(), communication_capabilities=[capability])
        result = analyze(request({"protocol_family": "dm-nvx"}), [source, target])
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")
        self.assertFalse(result["layers"]["restrictions"]["applicable"])

    def test_p18_hdmi_real(self):
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        hd = load_record("equipment/crestron/hd-md8x8-4kz-e.json")
        result = analyze(
            {
                "source": {"equipment_id": nvx["id"], "interface_id": "hdmi-output"},
                "target": {"equipment_id": hd["id"], "interface_id": "hdmi-in-1"},
                "requested_function": {"protocol_family": "hdmi"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [nvx, hd],
        )
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")

    def test_p19_aes67_real(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        nvx["catalog_coverage"] = {"communication_protocols": {"complete": True}}
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"},
                "requested_function": {"protocol_family": "aes67"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "COMPATIBLE")

    def test_p20_usb_exact_version(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "usb-a-1"},
                "target": {"equipment_id": nvx["id"], "interface_id": "usb-host"},
                "requested_function": {"protocol_family": "usb-2-0"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(result["layers"]["protocol"]["result"], "INCOMPATIBLE")

    def test_p21_dante_without_catalog_support(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"},
                "requested_function": {"protocol_family": "dante"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(result["layers"]["protocol"]["result"], "INCOMPATIBLE")

    def test_p22_optional_metadata_missing(self):
        source = equipment("source", signal=signal())
        target = equipment("target", signal=signal())
        self.assertEqual(self.protocol(source, target, "rs-232"), "INSUFFICIENT_DATA")

    def test_p23_mismatch_plus_unknown_is_insufficient(self):
        mismatch = {"id": "m", "name": "m", "signal_type": "control", "direction": "bidirectional", "protocol_family": "cec"}
        unknown = {"id": "u", "name": "u", "signal_type": "control", "direction": "bidirectional"}
        source = equipment("source", signal=None, interface={"signals": [mismatch, unknown]})
        target = equipment("target", signal=signal(protocol_family="rs-232"))
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertEqual(result["layers"]["protocol"]["result"], "INSUFFICIENT_DATA")

    def test_p24_final_aggregation_precedence(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["b"]}}
        source = equipment("source", signal=signal(protocol_family="rs-232"))
        target = equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface={"id": "b", "label": "b"})
        target["interfaces"].append({"id": "a", "label": "a", "direction": "bidirectional", "connector": "hdmi-type-a", "connector_gender": "female", "signals": [signal(protocol_family="rs-232")]})
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertEqual(result["layers"]["protocol"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_p25_other_signal_does_not_defeat_capability(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(protocol_family="cec"), communication_capabilities=[capability])
        target = equipment("target", signal=signal(protocol_family="rs-232"))
        self.assertEqual(self.protocol(source, target, "rs-232"), "COMPATIBLE")

    def test_p26_unavailable_plus_available_is_supported(self):
        missing = {"id": "missing", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "availability": "unavailable", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        present = {"id": "present", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(), communication_capabilities=[missing, present])
        target = equipment("target", signal=signal(), communication_capabilities=[present, missing])
        self.assertEqual(self.protocol(source, target, "rs-232"), "COMPATIBLE")

    def test_p27_conditional_plus_available_is_supported(self):
        conditional = {"id": "cond", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "availability": "conditional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        present = {"id": "present", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(), communication_capabilities=[conditional, present])
        target = equipment("target", signal=signal(), communication_capabilities=[present, conditional])
        self.assertEqual(self.protocol(source, target, "rs-232"), "COMPATIBLE")

    def test_p28_unavailable_plus_conditional_is_conditional(self):
        missing = {"id": "missing", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "availability": "unavailable", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        conditional = {"id": "cond", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "availability": "conditional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(), communication_capabilities=[missing, conditional])
        target = equipment("target", signal=signal(), communication_capabilities=[conditional, missing])
        self.assertEqual(self.protocol(source, target, "rs-232"), "CONDITIONALLY_COMPATIBLE")

    def test_p29_mismatch_plus_unknown_is_insufficient(self):
        mismatch = {"id": "m", "name": "m", "signal_type": "control", "direction": "bidirectional", "protocol_family": "cec"}
        unknown = {"id": "u", "name": "u", "signal_type": "control", "direction": "bidirectional"}
        source = equipment("source", signal=None, interface={"signals": [mismatch, unknown]})
        target = equipment("target", signal=None, interface={"signals": [mismatch, unknown]})
        self.assertEqual(self.protocol(source, target, "rs-232"), "INSUFFICIENT_DATA")

    def test_p30_all_routes_contradicted_is_incompatible(self):
        source = equipment("source", signal=signal(protocol_family="cec"))
        target = equipment("target", signal=signal(protocol_family="usb"))
        self.assertEqual(self.protocol(source, target, "rs-232"), "INCOMPATIBLE")

    def test_p31_configurable_capability_direction_is_compatible(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "configurable", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(direction="output"), communication_capabilities=[capability], interface=passive_supported())
        target = equipment("target", signal=signal(direction="input"), communication_capabilities=[capability], interface=passive_supported())
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "COMPATIBLE")

    def test_p32_configurable_conditional_availability(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "availability": "conditional", "interface_assignment": {"mode": "configurable", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(direction="output"), communication_capabilities=[capability], interface=passive_supported())
        target = equipment("target", signal=signal(direction="input"), communication_capabilities=[capability], interface=passive_supported())
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertEqual(result["layers"]["protocol"]["result"], "CONDITIONALLY_COMPATIBLE")
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "CONDITIONALLY_COMPATIBLE")


    def test_p32_configurable_conditional_availability(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "availability": "conditional", "interface_assignment": {"mode": "configurable", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(direction="output"), communication_capabilities=[capability], interface=passive_supported())
        target = equipment("target", signal=signal(direction="input"), communication_capabilities=[capability], interface=passive_supported())
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertEqual(result["layers"]["protocol"]["result"], "CONDITIONALLY_COMPATIBLE")
        self.assertEqual(result["layers"]["direction"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "CONDITIONALLY_COMPATIBLE")


class RestrictionsLayerV1Tests(unittest.TestCase):
    def check_restrictions(self, source, target, function=None, **kwargs):
        request_function = {"signal_family": "hdmi"}
        request_function.update(function or {})
        return analyze(
            request(request_function, **kwargs),
            [source, target],
        )["layers"]["restrictions"]

    def constrained(self, equipment_id, constraints):
        return equipment(equipment_id, signal=signal(), interface={"connection_constraints": constraints})

    def test_r01_no_constraints_not_applicable(self):
        layer = self.check_restrictions(equipment("source"), equipment("target"))
        self.assertFalse(layer["applicable"])

    def test_r02_allowed_exhaustive_manufacturer_match(self):
        constraints = {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"manufacturer": "target"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "COMPATIBLE")

    def test_r03_allowed_exhaustive_manufacturer_mismatch(self):
        constraints = {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"manufacturer": "other"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), self.constrained("target", constraints))
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r04_allowed_exhaustive_model_match(self):
        constraints = {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"model": "source"}]}}
        target = equipment("target", signal=signal(), interface={"connection_constraints": constraints})
        layer = self.check_restrictions(equipment("source"), target)
        self.assertEqual(layer["result"], "COMPATIBLE")

    def test_r05_allowed_exhaustive_model_mismatch(self):
        constraints = {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"model": "other"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), self.constrained("target", constraints))
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r06_allowed_exhaustive_product_family_match(self):
        source = {"id": "source", "manufacturer": "source", "model": "source", "product_family": "family", "interfaces": [{"id": "a", "label": "a", "direction": "bidirectional", "connector": "hdmi-type-a", "connector_gender": "female", "signals": [signal()]}]}
        target = {"id": "target", "manufacturer": "target", "model": "target", "product_family": "family", "interfaces": [{"id": "a", "label": "a", "direction": "bidirectional", "connector": "hdmi-type-a", "connector_gender": "female", "signals": [signal()], "connection_constraints": {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"product_family": "family"}]}}}]}
        result = analyze(request({"signal_family": "hdmi"}), [source, target])
        self.assertEqual(result["layers"]["restrictions"]["result"], "COMPATIBLE")

    def test_r07_allowed_exhaustive_equipment_id_match(self):
        constraints = {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"equipment_id": "target"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "COMPATIBLE")

    def test_r08_allowed_exhaustive_interface_id_match(self):
        constraints = {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"remote_interface_id": "a"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "COMPATIBLE")

    def test_r09_denied_manufacturer_match(self):
        constraints = {"id": "c", "denied_targets": {"targets": [{"manufacturer": "target"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r10_denied_manufacturer_nonmatch(self):
        constraints = {"id": "c", "denied_targets": {"targets": [{"manufacturer": "other"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "COMPATIBLE")

    def test_r11_denied_model_match(self):
        constraints = {"id": "c", "denied_targets": {"targets": [{"model": "target"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r12_conjunctive_selector_keys(self):
        constraints = {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"manufacturer": "target", "model": "other"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r13_allowed_selectors_are_or(self):
        constraints = {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"manufacturer": "other"}, {"manufacturer": "target"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "COMPATIBLE")

    def test_r14_denied_selectors_are_or(self):
        constraints = {"id": "c", "denied_targets": {"targets": [{"manufacturer": "other"}, {"manufacturer": "target"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r15_deny_wins_over_allow(self):
        constraints = {
            "id": "c",
            "allowed_targets": {"exhaustive": True, "targets": [{"manufacturer": "target"}]},
            "denied_targets": {"targets": [{"manufacturer": "target"}]},
        }
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r16_non_exhaustive_allow_miss_is_compatible(self):
        constraints = {"id": "c", "allowed_targets": {"exhaustive": False, "targets": [{"manufacturer": "other"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "COMPATIBLE")

    def test_r17_protocol_scope_matching_applies(self):
        constraints = {"id": "c", "protocol_family": "rs-232", "denied_targets": {"targets": [{"manufacturer": "target"}]}}
        layer = self.check_restrictions(
            self.constrained("source", constraints), equipment("target"), {"protocol_family": "rs-232"}
        )
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r18_protocol_scope_different_is_ignored(self):
        constraints = {"id": "c", "protocol_family": "rs-232", "denied_targets": {"targets": [{"manufacturer": "target"}]}}
        layer = self.check_restrictions(
            self.constrained("source", constraints), equipment("target"), {"protocol_family": "aes67"}
        )
        self.assertFalse(layer["applicable"])

    def test_r18b_protocol_scoped_without_protocol_request_is_ignored(self):
        constraints = {"id": "c", "protocol_family": "rs-232", "denied_targets": {"targets": [{"manufacturer": "target"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertFalse(layer["applicable"])

    def test_r19_source_restriction_only(self):
        constraints = {"id": "c", "denied_targets": {"targets": [{"manufacturer": "target"}]}}
        source = equipment("source", signal=signal(), interface={"connection_constraints": constraints})
        layer = self.check_restrictions(source, equipment("target"))
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r20_target_restriction_only(self):
        constraints = {"id": "c", "denied_targets": {"targets": [{"manufacturer": "source"}]}}
        target = equipment("target", signal=signal(), interface={"connection_constraints": constraints})
        layer = self.check_restrictions(equipment("source"), target)
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r21_bilateral_restrictions(self):
        source_constraints = {"id": "s", "denied_targets": {"targets": [{"manufacturer": "other"}]}}
        target_constraints = {"id": "t", "denied_targets": {"targets": [{"manufacturer": "other"}]}}
        source = equipment("source", signal=signal(), interface={"connection_constraints": source_constraints})
        target = equipment("target", signal=signal(), interface={"connection_constraints": target_constraints})
        layer = self.check_restrictions(source, target)
        self.assertEqual(layer["result"], "COMPATIBLE")

    def test_r22_remote_role_match(self):
        target = {
            "id": "target", "manufacturer": "target", "model": "target",
            "interfaces": [{"id": "a", "label": "a", "direction": "bidirectional", "connector": "hdmi-type-a", "connector_gender": "female", "role": "output", "signals": [signal()]}],
        }
        constraints = {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"remote_interface_role": "output"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), target)
        self.assertEqual(layer["result"], "COMPATIBLE")

    def test_r23_remote_role_mismatch(self):
        target = {
            "id": "target", "manufacturer": "target", "model": "target",
            "interfaces": [{"id": "a", "label": "a", "direction": "bidirectional", "connector": "hdmi-type-a", "connector_gender": "female", "role": "input", "signals": [signal()]}],
        }
        constraints = {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"remote_interface_role": "output"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), target)
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r24_remote_role_missing_is_insufficient(self):
        constraints = {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"remote_interface_role": "output"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "INSUFFICIENT_DATA")

    def test_r25_role_selector_unknown_not_mismatch(self):
        constraints = {
            "id": "c",
            "allowed_targets": {"exhaustive": True, "targets": [{"manufacturer": "other"}, {"remote_interface_role": "output"}]},
        }
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "INSUFFICIENT_DATA")

    def test_r26_protocol_compatible_restrictions_incompatible(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        constraints = {"id": "c", "denied_targets": {"targets": [{"manufacturer": "target"}]}}
        source = equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface={"connection_constraints": constraints, **passive_supported()})
        target = equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface=passive_supported())
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")
        self.assertEqual(result["layers"]["restrictions"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_r27_signal_compatible_restrictions_incompatible(self):
        constraints = {"id": "c", "denied_targets": {"targets": [{"manufacturer": "target"}]}}
        source = equipment("source", signal=signal(), interface={"connection_constraints": constraints, **passive_supported()})
        target = equipment("target", signal=signal(), interface=passive_supported())
        result = analyze(request({"signal_family": "hdmi"}), [source, target])
        self.assertEqual(result["layers"]["signal"]["result"], "COMPATIBLE")
        self.assertEqual(result["layers"]["restrictions"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_r28_known_compatibility_does_not_override_deny(self):
        source = equipment(
            "source",
            signal=signal(protocol_family="rs-232"),
            interface={"connection_constraints": {"id": "deny", "denied_targets": {"targets": [{"equipment_id": "target"}]}}},
            known_compatibilities=[{"id": "known", "relation": "compatible", "target_equipment_id": "target", "local_interface_id": "a", "protocol_family": "rs-232"}],
        )
        target = equipment("target", signal=signal(protocol_family="rs-232"))
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertEqual(result["layers"]["restrictions"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")
        self.assertTrue(result["evidence"])

    def test_r29_known_compatibility_absence_no_penalty(self):
        layer = self.check_restrictions(equipment("source"), equipment("target"))
        self.assertFalse(layer["applicable"])

    def test_r30_proprietary_without_constraints_not_applicable(self):
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        core = load_record("equipment/qsys/core-8-flex.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"},
                "requested_function": {"protocol_family": "dm-nvx"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertFalse(result["layers"]["restrictions"]["applicable"])

    def test_r31_allow_mismatch_plus_unknown_is_insufficient(self):
        constraints = {
            "id": "c",
            "allowed_targets": {"exhaustive": True, "targets": [{"manufacturer": "other"}, {"remote_interface_role": "output"}]},
        }
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "INSUFFICIENT_DATA")

    def test_r32_deny_mismatch_plus_unknown_is_insufficient(self):
        constraints = {"id": "c", "denied_targets": {"targets": [{"manufacturer": "other"}, {"remote_interface_role": "output"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "INSUFFICIENT_DATA")

    def test_r33_deny_match_plus_unknown_is_incompatible(self):
        constraints = {"id": "c", "denied_targets": {"targets": [{"manufacturer": "target"}, {"remote_interface_role": "output"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r34_allow_match_plus_deny_mismatch_is_compatible(self):
        constraints = {
            "id": "c",
            "allowed_targets": {"exhaustive": True, "targets": [{"manufacturer": "target"}]},
            "denied_targets": {"targets": [{"manufacturer": "other"}]},
        }
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "COMPATIBLE")

    def test_r35_allow_match_plus_deny_match_is_incompatible(self):
        constraints = {
            "id": "c",
            "allowed_targets": {"exhaustive": True, "targets": [{"manufacturer": "target"}]},
            "denied_targets": {"targets": [{"manufacturer": "target"}]},
        }
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r36_conjunctive_selector_keys(self):
        constraints = {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"manufacturer": "target", "model": "target"}]}}
        layer = self.check_restrictions(self.constrained("source", constraints), equipment("target"))
        self.assertEqual(layer["result"], "COMPATIBLE")
        mismatch = {"id": "c", "allowed_targets": {"exhaustive": True, "targets": [{"manufacturer": "target", "model": "other"}]}}
        layer = self.check_restrictions(self.constrained("source", mismatch), equipment("target"))
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_r37_real_catalog_has_no_restrictions(self):
        for path in ["equipment/qsys/core-8-flex.json", "equipment/crestron/dm-nvx-360c.json", "equipment/crestron/hd-md8x8-4kz-e.json", "equipment/crestron/dmf-ci-8.json"]:
            record = load_record(path)
            for interface in record.get("interfaces", []):
                self.assertNotIn("connection_constraints", interface)


class CapacityLayerV1Tests(unittest.TestCase):
    def capacity(self, source, target, requirement, function=None, **kwargs):
        request_function = {"signal_family": "ethernet", "capacity_requirement": requirement}
        request_function.update(function or {})
        return analyze(
            request(request_function, **kwargs),
            [source, target],
        )["layers"]["capacity"]

    def capped(self, equipment_id, capacity=None, pool_id=None, pools=None, protocol=None, assignment=None):
        capability = {"id": "cap", "type": "data", "direction": "bidirectional"}
        if protocol is not None:
            capability["protocol_family"] = protocol
        if capacity is not None:
            capability["capacity"] = capacity
        if pool_id is not None:
            capability["resource_pool_id"] = pool_id
        capability["interface_assignment"] = assignment or {"mode": "fixed", "allowed_interface_ids": ["a"]}
        record = equipment(equipment_id, signal=signal(signal_type="network", signal_family="ethernet"), communication_capabilities=[capability])
        if pools is not None:
            record["resource_pools"] = pools
        return record

    def test_c01_no_requirement_not_applicable(self):
        result = analyze(request({"signal_family": "ethernet"}), [equipment("source"), equipment("target")])
        self.assertFalse(result["layers"]["capacity"]["applicable"])

    def test_c02_sufficient_exact_capacity(self):
        source = self.capped("source", capacity={"rx_channels": 4})
        target = self.capped("target", capacity={"rx_channels": 4})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 4})["result"], "COMPATIBLE")

    def test_c03_insufficient_exact_capacity(self):
        source = self.capped("source", capacity={"rx_channels": 2})
        target = self.capped("target", capacity={"rx_channels": 2})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 4})["result"], "INCOMPATIBLE")

    def test_c04_missing_capacity_data(self):
        self.assertEqual(self.capacity(equipment("source"), equipment("target"), {"rx_channels": 4})["result"], "INSUFFICIENT_DATA")

    def test_c05_zero_capacity(self):
        source = self.capped("source", capacity={"rx_channels": 0})
        target = self.capped("target", capacity={"rx_channels": 0})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 1})["result"], "INCOMPATIBLE")

    def test_c06_exact_boundary_equal(self):
        source = self.capped("source", capacity={"sessions": 2})
        target = self.capped("target", capacity={"sessions": 2})
        self.assertEqual(self.capacity(source, target, {"sessions": 2})["result"], "COMPATIBLE")

    def test_c07_sufficient_plus_insufficient_routes(self):
        low = {"id": "low", "type": "data", "direction": "bidirectional", "capacity": {"rx_channels": 2}, "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        high = {"id": "high", "type": "data", "direction": "bidirectional", "capacity": {"rx_channels": 8}, "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), communication_capabilities=[low, high])
        target = self.capped("target", capacity={"rx_channels": 8})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 4})["result"], "COMPATIBLE")

    def test_c08_insufficient_plus_unknown_routes(self):
        low = {"id": "low", "type": "data", "direction": "bidirectional", "capacity": {"rx_channels": 2}, "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        bare = {"id": "bare", "type": "data", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), communication_capabilities=[low, bare])
        target = self.capped("target", capacity={"rx_channels": 8})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 4})["result"], "INSUFFICIENT_DATA")

    def test_c09_sufficient_plus_unknown_routes(self):
        bare = {"id": "bare", "type": "data", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        high = {"id": "high", "type": "data", "direction": "bidirectional", "capacity": {"rx_channels": 8}, "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), communication_capabilities=[bare, high])
        target = self.capped("target", capacity={"rx_channels": 8})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 4})["result"], "COMPATIBLE")

    def test_c10_shared_pool_not_summed(self):
        pools = [{"id": "pool", "resources": {"rx_channels": 4}}]
        source = self.capped("source", pool_id="pool", pools=pools)
        target = self.capped("target", pool_id="pool", pools=pools)
        self.assertEqual(self.capacity(source, target, {"rx_channels": 8})["result"], "INCOMPATIBLE")

    def test_c11_capability_pool_effective_min(self):
        pools = [{"id": "pool", "resources": {"rx_channels": 8}}]
        source = self.capped("source", capacity={"rx_channels": 16}, pool_id="pool", pools=pools)
        target = self.capped("target", capacity={"rx_channels": 16}, pool_id="pool", pools=pools)
        self.assertEqual(self.capacity(source, target, {"rx_channels": 12})["result"], "INCOMPATIBLE")
        self.assertEqual(self.capacity(source, target, {"rx_channels": 8})["result"], "COMPATIBLE")

    def test_c12_pool_only_capacity(self):
        pools = [{"id": "pool", "resources": {"streams": 32}}]
        source = self.capped("source", pool_id="pool", pools=pools)
        target = self.capped("target", pool_id="pool", pools=pools)
        self.assertEqual(self.capacity(source, target, {"streams": 20})["result"], "COMPATIBLE")

    def test_c13_capability_only_capacity(self):
        source = self.capped("source", capacity={"sessions": 2})
        target = self.capped("target", capacity={"sessions": 2})
        self.assertEqual(self.capacity(source, target, {"sessions": 2})["result"], "COMPATIBLE")
        self.assertEqual(self.capacity(source, target, {"sessions": 3})["result"], "INCOMPATIBLE")

    def test_c14_broken_pool_otherwise_sufficient(self):
        source = self.capped("source", capacity={"rx_channels": 8}, pool_id="missing")
        target = self.capped("target", capacity={"rx_channels": 8})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 4})["result"], "INSUFFICIENT_DATA")

    def test_c15_broken_pool_explicit_insufficient(self):
        source = self.capped("source", capacity={"rx_channels": 2}, pool_id="missing")
        target = self.capped("target", capacity={"rx_channels": 8})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 4})["result"], "INCOMPATIBLE")

    def test_c16_source_target_sufficient(self):
        source = self.capped("source", capacity={"rx_channels": 8})
        target = self.capped("target", capacity={"rx_channels": 8})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 8})["result"], "COMPATIBLE")

    def test_c17_source_insufficient(self):
        source = self.capped("source", capacity={"rx_channels": 2})
        target = self.capped("target", capacity={"rx_channels": 8})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 4})["result"], "INCOMPATIBLE")

    def test_c18_target_insufficient(self):
        source = self.capped("source", capacity={"rx_channels": 8})
        target = self.capped("target", capacity={"rx_channels": 2})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 4})["result"], "INCOMPATIBLE")

    def test_c19_source_unknown_target_sufficient(self):
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"))
        target = self.capped("target", capacity={"rx_channels": 8})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 4})["result"], "INSUFFICIENT_DATA")

    def test_c20_source_unknown_target_contradicted(self):
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"))
        target = self.capped("target", capacity={"rx_channels": 2})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 4})["result"], "INCOMPATIBLE")

    def test_c21_configurable_no_conditional(self):
        assignment = {"mode": "configurable", "allowed_interface_ids": ["a"]}
        source = self.capped("source", capacity={"rx_channels": 8}, assignment=assignment)
        target = self.capped("target", capacity={"rx_channels": 8}, assignment=assignment)
        layer = self.capacity(source, target, {"rx_channels": 4})
        self.assertEqual(layer["result"], "COMPATIBLE")
        self.assertNotEqual(layer["result"], "CONDITIONALLY_COMPATIBLE")

    def test_c22_simultaneous_no_arithmetic(self):
        assignment = {"mode": "simultaneous", "allowed_interface_ids": ["a", "b"]}
        source = self.capped("source", capacity={"rx_channels": 8}, assignment=assignment)
        target = self.capped("target", capacity={"rx_channels": 8}, assignment=assignment)
        self.assertEqual(self.capacity(source, target, {"rx_channels": 8})["result"], "COMPATIBLE")

    def test_c23_redundant_no_arithmetic(self):
        assignment = {"mode": "redundant", "allowed_interface_ids": ["a", "b"]}
        source = self.capped("source", capacity={"rx_channels": 8}, assignment=assignment)
        target = self.capped("target", capacity={"rx_channels": 8}, assignment=assignment)
        self.assertEqual(self.capacity(source, target, {"rx_channels": 8})["result"], "COMPATIBLE")

    def test_c24_segregated_no_arithmetic(self):
        assignment = {"mode": "segregated", "allowed_interface_ids": ["a", "b"]}
        source = self.capped("source", capacity={"rx_channels": 8}, assignment=assignment)
        target = self.capped("target", capacity={"rx_channels": 8}, assignment=assignment)
        self.assertEqual(self.capacity(source, target, {"rx_channels": 8})["result"], "COMPATIBLE")

    def test_c25_protocol_scoped_discovery(self):
        source = self.capped("source", capacity={"rx_channels": 8}, protocol="aes67")
        target = self.capped("target", capacity={"rx_channels": 8}, protocol="aes67")
        layer = self.capacity(source, target, {"rx_channels": 4}, {"protocol_family": "aes67"})
        self.assertEqual(layer["result"], "COMPATIBLE")

    def test_c26_protocol_unrelated_ignored(self):
        source = self.capped("source", capacity={"rx_channels": 8}, protocol="dante")
        target = self.capped("target", capacity={"rx_channels": 8}, protocol="dante")
        layer = self.capacity(source, target, {"rx_channels": 4}, {"protocol_family": "aes67"})
        self.assertEqual(layer["result"], "INSUFFICIENT_DATA")

    def test_c27_no_protocol_order_independence(self):
        low = {"id": "low", "type": "data", "direction": "bidirectional", "capacity": {"rx_channels": 2}, "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        high = {"id": "high", "type": "data", "direction": "bidirectional", "capacity": {"rx_channels": 8}, "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), communication_capabilities=[low, high])
        target = self.capped("target", capacity={"rx_channels": 8})
        forward = analyze(request({"signal_family": "ethernet", "capacity_requirement": {"rx_channels": 4}}), [source, target])
        source["communication_capabilities"] = [high, low]
        reversed_order = analyze(request({"signal_family": "ethernet", "capacity_requirement": {"rx_channels": 4}}), [source, target])
        self.assertEqual(forward["layers"]["capacity"]["result"], "COMPATIBLE")
        self.assertEqual(forward["result"], reversed_order["result"])

    def test_c28_no_protocol_insufficient_plus_unknown(self):
        low = {"id": "low", "type": "data", "direction": "bidirectional", "capacity": {"rx_channels": 2}, "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        bare = {"id": "bare", "type": "data", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), communication_capabilities=[low, bare])
        target = self.capped("target", capacity={"rx_channels": 8})
        result = analyze(request({"signal_family": "ethernet", "capacity_requirement": {"rx_channels": 4}}), [source, target])
        self.assertEqual(result["layers"]["capacity"]["result"], "INSUFFICIENT_DATA")

    def test_c29_no_protocol_sufficient_plus_unknown(self):
        bare = {"id": "bare", "type": "data", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        high = {"id": "high", "type": "data", "direction": "bidirectional", "capacity": {"rx_channels": 8}, "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), communication_capabilities=[bare, high])
        target = self.capped("target", capacity={"rx_channels": 8})
        result = analyze(request({"signal_family": "ethernet", "capacity_requirement": {"rx_channels": 4}}), [source, target])
        self.assertEqual(result["layers"]["capacity"]["result"], "COMPATIBLE")

    def test_c30_multidimension_same_route(self):
        source = self.capped("source", capacity={"rx_channels": 8, "streams": 4})
        target = self.capped("target", capacity={"rx_channels": 8, "streams": 4})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 8, "streams": 4})["result"], "COMPATIBLE")

    def test_c31_dimensions_not_composed_across_routes(self):
        route_a = {"id": "a", "type": "data", "direction": "bidirectional", "capacity": {"rx_channels": 8, "streams": 2}, "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        route_b = {"id": "b", "type": "data", "direction": "bidirectional", "capacity": {"rx_channels": 4, "streams": 4}, "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), communication_capabilities=[route_a, route_b])
        target = self.capped("target", capacity={"rx_channels": 8, "streams": 4})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 8, "streams": 4})["result"], "INCOMPATIBLE")

    def test_c32_unsupported_bandwidth_dimension(self):
        source = self.capped("source", capacity={"rx_channels": 64})
        target = self.capped("target", capacity={"rx_channels": 64})
        layer = self.capacity(source, target, {"bandwidth": 100})
        self.assertEqual(layer["result"], "INSUFFICIENT_DATA")

    def test_c33_unsupported_arbitrary_dimension(self):
        source = self.capped("source", capacity={"rx_channels": 64})
        target = self.capped("target", capacity={"rx_channels": 64})
        layer = self.capacity(source, target, {"flows": 4})
        self.assertEqual(layer["result"], "INSUFFICIENT_DATA")

    def test_c34_zero_requirement_zero_capacity(self):
        source = self.capped("source", capacity={"rx_channels": 0})
        target = self.capped("target", capacity={"rx_channels": 0})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 0})["result"], "COMPATIBLE")

    def test_c35_shared_pool_multiple_capabilities(self):
        first = {"id": "first", "type": "data", "direction": "bidirectional", "resource_pool_id": "pool", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        second = {"id": "second", "type": "data", "direction": "bidirectional", "resource_pool_id": "pool", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        pools = [{"id": "pool", "resources": {"rx_channels": 4}}]
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), communication_capabilities=[first, second])
        source["resource_pools"] = pools
        target = self.capped("target", capacity={"rx_channels": 4})
        self.assertEqual(self.capacity(source, target, {"rx_channels": 8})["result"], "INCOMPATIBLE")
        self.assertEqual(self.capacity(source, target, {"rx_channels": 4})["result"], "COMPATIBLE")

    def test_c36_real_dante_effective_eight(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        nvx["catalog_coverage"] = {"communication_protocols": {"complete": True}}
        eight = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "target": {"equipment_id": core["id"], "interface_id": "lan-b"},
                "requested_function": {"protocol_family": "dante", "capacity_requirement": {"rx_channels": 8}},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(eight["layers"]["capacity"]["result"], "COMPATIBLE")
        nine = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "target": {"equipment_id": core["id"], "interface_id": "lan-b"},
                "requested_function": {"protocol_family": "dante", "capacity_requirement": {"rx_channels": 9}},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(nine["layers"]["capacity"]["result"], "INCOMPATIBLE")

    def test_c37_real_aes67_rx2_compatible(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"},
                "requested_function": {"protocol_family": "aes67", "capacity_requirement": {"rx_channels": 2}},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(result["layers"]["capacity"]["result"], "COMPATIBLE")

    def test_c38_real_aes67_rx4_incompatible(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"},
                "requested_function": {"protocol_family": "aes67", "capacity_requirement": {"rx_channels": 4}},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(result["layers"]["capacity"]["result"], "INCOMPATIBLE")

    def test_c39_real_aes67_streams40_contradicted(self):
        # Core pool streams ceiling (32) explicitly contradicts streams=40;
        # per global precedence an explicit contradiction wins over the
        # NVX-side unknown (NVX declares no streams dimension).
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"},
                "requested_function": {"protocol_family": "aes67", "capacity_requirement": {"streams": 40}},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(result["layers"]["capacity"]["result"], "INCOMPATIBLE")

    def test_c40_hdmd_requirement_insufficient(self):
        hd = load_record("equipment/crestron/hd-md8x8-4kz-e.json")
        core = load_record("equipment/qsys/core-8-flex.json")
        result = analyze(
            {
                "source": {"equipment_id": hd["id"], "interface_id": "lan"},
                "target": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "requested_function": {"signal_family": "ethernet", "capacity_requirement": {"rx_channels": 2}},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [hd, core],
        )
        self.assertEqual(result["layers"]["capacity"]["result"], "INSUFFICIENT_DATA")

    def test_c41_dmf_slots_not_capacity(self):
        chassis = load_record("equipment/crestron/dmf-ci-8.json")
        core = load_record("equipment/qsys/core-8-flex.json")
        result = analyze(
            {
                "source": {"equipment_id": chassis["id"], "interface_id": "console-serial"},
                "target": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "requested_function": {"signal_family": "ethernet", "capacity_requirement": {"rx_channels": 2}},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [chassis, core],
        )
        self.assertEqual(result["layers"]["capacity"]["result"], "INSUFFICIENT_DATA")

    def test_c42_modifiers_not_applied(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "target": {"equipment_id": core["id"], "interface_id": "lan-b"},
                "requested_function": {"protocol_family": "dante", "capacity_requirement": {"rx_channels": 16}},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(result["layers"]["capacity"]["result"], "INCOMPATIBLE")


    def test_c43_contradicted_supported_dimension_plus_unsupported_dimension(self):
        source = self.capped("source", capacity={"rx_channels": 8})
        target = self.capped("target", capacity={"rx_channels": 8})
        layer = self.capacity(source, target, {"rx_channels": 10, "bandwidth": 100})
        self.assertEqual(layer["result"], "INCOMPATIBLE")

    def test_c44_supported_plus_unsupported_dimension_without_contradiction(self):
        source = self.capped("source", capacity={"rx_channels": 64})
        target = self.capped("target", capacity={"rx_channels": 64})
        layer = self.capacity(source, target, {"rx_channels": 2, "bandwidth": 100})
        self.assertEqual(layer["result"], "INSUFFICIENT_DATA")


class IntegratedAnalyzerV1Tests(unittest.TestCase):
    def hdmi_pair(self, source_direction="output", target_direction="input", source_extra=None, target_extra=None):
        source_signal = {"id": "s", "name": "s", "signal_type": "video", "signal_family": "hdmi", "direction": source_direction}
        target_signal = {"id": "s", "name": "s", "signal_type": "video", "signal_family": "hdmi", "direction": target_direction}
        if source_extra:
            source_signal.update(source_extra)
        if target_extra:
            target_signal.update(target_extra)
        source = equipment("source", signal=None, interface={"signals": [source_signal], **passive_supported()})
        target = equipment("target", signal=None, interface={"signals": [target_signal], **passive_supported()})
        return source, target

    def test_i01_final_all_compatible(self):
        source, target = self.hdmi_pair()
        result = analyze(request({"signal_family": "hdmi"}), [source, target])
        self.assertEqual(result["result"], "COMPATIBLE")

    def test_i02_compatible_plus_not_applicable(self):
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), interface=passive_supported())
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), interface=passive_supported())
        result = analyze(request({"signal_family": "ethernet"}), [source, target])
        self.assertFalse(result["layers"]["electrical"]["applicable"])
        self.assertFalse(result["layers"]["protocol"]["applicable"])
        self.assertEqual(result["result"], "COMPATIBLE")

    def test_i03_incompatible_plus_compatible(self):
        source, target = self.hdmi_pair(source_direction="input", target_direction="input")
        result = analyze(request({"signal_family": "hdmi"}), [source, target])
        self.assertEqual(result["layers"]["direction"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_i04_incompatible_plus_insufficient(self):
        source = equipment(
            "source", signal=None,
            interface={"signals": [{"id": "s", "name": "s", "signal_type": "video", "signal_family": "hdmi", "direction": "input"}], **passive_supported()},
        )
        target = {"id": "target", "manufacturer": "target", "model": "target", "interfaces": [{"id": "a", "label": "a", "direction": "output", "connector": "hdmi-type-a", "connector_gender": "female", **passive_supported()}]}
        result = analyze(request({"signal_family": "hdmi"}), [source, target])
        self.assertEqual(result["layers"]["signal"]["result"], "INSUFFICIENT_DATA")
        self.assertEqual(result["layers"]["direction"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_i05_incompatible_plus_conditional(self):
        capability = {"id": "c", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "availability": "conditional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(direction="input", protocol_family="rs-232"), communication_capabilities=[capability], interface=passive_supported())
        target = equipment("target", signal=signal(direction="input", protocol_family="rs-232"), communication_capabilities=[capability], interface=passive_supported())
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertEqual(result["layers"]["direction"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["layers"]["protocol"]["result"], "CONDITIONALLY_COMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_i06_insufficient_plus_compatible(self):
        source = equipment("source", signal=signal(signal_type="audio", signal_family="analog-audio", direction="output"), interface=passive_supported())
        target = equipment("target", signal=signal(signal_type="audio", signal_family="analog-audio", direction="input"), interface=passive_supported())
        result = analyze(request({"signal_family": "analog-audio"}), [source, target])
        self.assertEqual(result["layers"]["electrical"]["result"], "INSUFFICIENT_DATA")
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_i07_insufficient_plus_conditional(self):
        capability = {"id": "c", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "availability": "conditional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=None, interface={"signals": []}, communication_capabilities=[capability])
        target = equipment("target", signal=None, interface={"signals": []}, communication_capabilities=[capability])
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertFalse(result["layers"]["signal"]["applicable"])
        self.assertEqual(result["layers"]["physical"]["result"], "INSUFFICIENT_DATA")
        self.assertEqual(result["layers"]["protocol"]["result"], "CONDITIONALLY_COMPATIBLE")
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_i08_conditional_plus_compatible(self):
        capability = {"id": "c", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "availability": "conditional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(direction="output", protocol_family="rs-232"), communication_capabilities=[capability], interface=passive_supported())
        target = equipment("target", signal=signal(direction="input", protocol_family="rs-232"), communication_capabilities=[capability], interface=passive_supported())
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertEqual(result["layers"]["protocol"]["result"], "CONDITIONALLY_COMPATIBLE")
        self.assertEqual(result["result"], "CONDITIONALLY_COMPATIBLE")

    def test_i09_all_not_applicable_aggregator(self):
        from compatibility.analyze import _aggregate
        layers = {name: {"applicable": False} for name in ("physical", "electrical", "signal", "protocol", "direction", "restrictions", "capacity")}
        self.assertEqual(_aggregate(layers), "COMPATIBLE")

    def test_i10_two_incompatible_layers(self):
        coverage = {"communication_protocols": {"complete": True}}
        source = equipment("source", signal=signal(signal_family="analog-audio", protocol_family="usb"), catalog_coverage=coverage, interface=passive_supported())
        target = equipment("target", signal=signal(signal_family="analog-audio", protocol_family="cec"), catalog_coverage=coverage, interface=passive_supported())
        result = analyze(request({"signal_family": "hdmi", "protocol_family": "rs-232"}), [source, target])
        self.assertEqual(result["layers"]["signal"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["layers"]["protocol"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_i11_aggregator_order_independence(self):
        from compatibility.analyze import _aggregate
        import itertools
        states = [
            {"applicable": True, "result": "COMPATIBLE", "reasons": []},
            {"applicable": True, "result": "INSUFFICIENT_DATA", "reasons": []},
            {"applicable": True, "result": "INCOMPATIBLE", "reasons": []},
        ]
        for permutation in itertools.permutations(states):
            layers = {f"layer{i}": dict(layer) for i, layer in enumerate(permutation)}
            self.assertEqual(_aggregate(layers), "INCOMPATIBLE")
        without_incompatible = [layer for layer in states if layer["result"] != "INCOMPATIBLE"]
        for permutation in itertools.permutations(without_incompatible):
            layers = {f"layer{i}": dict(layer) for i, layer in enumerate(permutation)}
            self.assertEqual(_aggregate(layers), "INSUFFICIENT_DATA")

    def test_i12_reason_preservation(self):
        source = equipment("source", signal=signal(protocol_family="usb"), interface=passive_supported())
        target = equipment("target", signal=signal(protocol_family="cec"), interface=passive_supported())
        result = analyze(request({"signal_family": "hdmi", "protocol_family": "rs-232"}), [source, target])
        signal_reasons = result["layers"]["signal"]["reasons"]
        protocol_reasons = result["layers"]["protocol"]["reasons"]
        for reason in signal_reasons + protocol_reasons:
            self.assertIn(reason, result["reasons"])

    def test_i13_not_applicable_neutrality(self):
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), interface=passive_supported())
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), interface=passive_supported())
        result = analyze(request({"signal_family": "ethernet"}), [source, target])
        not_applicable = [name for name, layer in result["layers"].items() if not layer["applicable"]]
        self.assertTrue(not_applicable)
        self.assertEqual(result["result"], "COMPATIBLE")

    def test_i14_signal_ambiguity_plus_independent_deny(self):
        first = {"id": "first", "name": "first", "signal_type": "video", "signal_family": "hdmi", "direction": "output"}
        second = {"id": "second", "name": "second", "signal_type": "video", "signal_family": "hdmi", "direction": "output"}
        source = equipment(
            "source", signal=None,
            interface={"signals": [first, second], "connection_constraints": {"id": "deny", "denied_targets": {"targets": [{"equipment_id": "target"}]}}, **passive_supported()},
        )
        target = equipment("target", signal=signal(direction="input"), interface=passive_supported())
        result = analyze(request({"signal_family": "hdmi"}), [source, target])
        self.assertEqual(result["layers"]["direction"]["result"], "INSUFFICIENT_DATA")
        self.assertEqual(result["layers"]["restrictions"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_i15_physical_unknown_plus_protocol_incompatible(self):
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c")
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), connector="rj45-8p8c")
        result = analyze(request({"protocol_family": "dante"}), [source, target])
        self.assertEqual(result["layers"]["physical"]["result"], "INSUFFICIENT_DATA")
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_i16_capacity_incompatible_plus_unknown(self):
        low = {"id": "low", "type": "data", "direction": "bidirectional", "capacity": {"streams": 32}, "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(signal_type="network", signal_family="ethernet"), communication_capabilities=[low], interface=passive_supported())
        target = equipment("target", signal=signal(signal_type="network", signal_family="ethernet"), interface=passive_supported())
        result = analyze(request({"signal_family": "ethernet", "capacity_requirement": {"streams": 40}}), [source, target])
        self.assertEqual(result["layers"]["capacity"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_i17_restrictions_incompatible_plus_unknown(self):
        source = equipment(
            "source", signal=None,
            interface={"signals": [{"id": "s", "name": "s", "signal_type": "video", "direction": "output"}], "connection_constraints": {"id": "deny", "denied_targets": {"targets": [{"equipment_id": "target"}]}}, **passive_supported()},
        )
        target = equipment("target", signal=signal(direction="input"), interface=passive_supported())
        result = analyze(request({"signal_family": "hdmi"}), [source, target])
        self.assertEqual(result["layers"]["signal"]["result"], "INSUFFICIENT_DATA")
        self.assertEqual(result["layers"]["restrictions"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_i18_real_analog_compatible(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "flex-1"},
                "target": {"equipment_id": nvx["id"], "interface_id": "audio-io"},
                "requested_function": {"signal_family": "analog-audio"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        for layer in ("physical", "electrical", "signal", "direction"):
            self.assertEqual(result["layers"][layer]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "COMPATIBLE")

    def test_i19_real_aes67_compatible(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"},
                "requested_function": {"protocol_family": "aes67"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")
        self.assertEqual(result["result"], "COMPATIBLE")

    def test_i20_real_rs232_insufficient(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        chassis = load_record("equipment/crestron/dmf-ci-8.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "rs232-1"},
                "target": {"equipment_id": chassis["id"], "interface_id": "console-serial"},
                "requested_function": {"protocol_family": "rs-232"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, chassis],
        )
        self.assertEqual(result["layers"]["protocol"]["result"], "COMPATIBLE")
        self.assertEqual(result["layers"]["physical"]["result"], "INSUFFICIENT_DATA")
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_i21_real_usb_incompatible(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "usb-a-1"},
                "target": {"equipment_id": nvx["id"], "interface_id": "usb-host"},
                "requested_function": {"protocol_family": "usb-2-0"},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(result["layers"]["protocol"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_i22_real_capacity_incompatible(self):
        core = load_record("equipment/qsys/core-8-flex.json")
        nvx = load_record("equipment/crestron/dm-nvx-360c.json")
        result = analyze(
            {
                "source": {"equipment_id": core["id"], "interface_id": "lan-a"},
                "target": {"equipment_id": nvx["id"], "interface_id": "ethernet-1"},
                "requested_function": {"protocol_family": "aes67", "capacity_requirement": {"streams": 40}},
                "analysis_scope": "CATALOG",
                "interconnect_assumption": "APPROPRIATE_MEDIUM",
            },
            [core, nvx],
        )
        self.assertEqual(result["layers"]["capacity"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_i23_no_semantic_short_circuit(self):
        low = {"id": "low", "type": "data", "direction": "bidirectional", "protocol_family": "rs-232", "availability": "unavailable", "capacity": {"streams": 32}, "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(protocol_family="usb"), communication_capabilities=[low], interface=passive_supported())
        target = equipment("target", signal=signal(protocol_family="cec"), communication_capabilities=[low], interface=passive_supported())
        result = analyze(
            request({"signal_family": "hdmi", "protocol_family": "rs-232", "capacity_requirement": {"streams": 40}}),
            [source, target],
        )
        self.assertEqual(result["layers"]["protocol"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["layers"]["capacity"]["result"], "INCOMPATIBLE")
        self.assertEqual(result["result"], "INCOMPATIBLE")

    def test_i24_errors_vs_insufficient(self):
        with self.assertRaises(AnalysisInputError):
            analyze(
                {"source": {"equipment_id": "missing", "interface_id": "a"}, "target": {"equipment_id": "target", "interface_id": "a"}, "requested_function": {"signal_family": "hdmi"}, "analysis_scope": "CATALOG", "interconnect_assumption": "APPROPRIATE_MEDIUM"},
                [equipment("target")],
            )
        with self.assertRaises(AnalysisInputError):
            analyze(
                {"source": {"equipment_id": "source", "interface_id": "missing"}, "target": {"equipment_id": "target", "interface_id": "a"}, "requested_function": {"signal_family": "hdmi"}, "analysis_scope": "CATALOG", "interconnect_assumption": "APPROPRIATE_MEDIUM"},
                [equipment("source"), equipment("target")],
            )
        with self.assertRaises(AnalysisInputError):
            analyze(
                {"source": {"equipment_id": "source", "interface_id": "a"}, "target": {"equipment_id": "target", "interface_id": "a"}, "analysis_scope": "CATALOG", "interconnect_assumption": "APPROPRIATE_MEDIUM"},
                [equipment("source"), equipment("target")],
            )
        result = analyze(request({"signal_family": "hdmi"}), [equipment("source"), equipment("target", signal=None, interface={"signals": []})])
        self.assertEqual(result["result"], "INSUFFICIENT_DATA")

    def test_i25_evidence_supplemental_shape(self):
        capability = {"id": "cap", "type": "control", "protocol_family": "rs-232", "direction": "bidirectional", "interface_assignment": {"mode": "fixed", "allowed_interface_ids": ["a"]}}
        source = equipment("source", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface=passive_supported())
        target = equipment("target", signal=signal(protocol_family="rs-232"), communication_capabilities=[capability], interface=passive_supported())
        result = analyze(request({"protocol_family": "rs-232"}), [source, target])
        self.assertIsInstance(result["evidence"], list)
        self.assertTrue(result["evidence"])
        self.assertEqual(result["result"], "COMPATIBLE")


if __name__ == "__main__":
    unittest.main()
