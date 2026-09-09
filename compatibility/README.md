# AVForge Compatibility Analyzer v0.1

This package provides the first conservative implementation of the contract
defined in [`docs/compatibility-analyzer-contract.md`](../docs/compatibility-analyzer-contract.md).

## Scope

Only `CATALOG` analysis is supported. The analyzer evaluates a source
interface, target interface, and `requested_function` using the catalog records
explicitly supplied by the caller. It does not make project connection
decisions.

The analyzer uses open-world semantics: absence of a declared protocol or
capability is not proof of non-support. Required missing evidence produces
`INSUFFICIENT_DATA`; `INCOMPATIBLE` requires explicit contrary evidence.

For Schema v3.4 records, `catalog_coverage.communication_protocols.complete`
is an explicit exception scoped to the communication-protocol domain. When it
is `true`, an absent requested protocol is absent from the complete official
catalog scope and produces `INCOMPATIBLE`. Missing or false coverage preserves
`INSUFFICIENT_DATA`. An explicitly present protocol is always analyzed through
its capability, assignment, availability, and restrictions regardless of
coverage. Coverage does not infer protocols from connectors or Ethernet and
does not cover module capabilities installed in a chassis.

The caller is expected to provide records that have already passed JSON Schema
and Semantic Validator checks. The analyzer resolves equipment and interface
IDs in the supplied set but does not implement a catalog service or duplicate
semantic validation.

## Input and Output

The Python API is:

```python
from compatibility.analyze import analyze

result = analyze(request, equipment_records)
```

The request requires `source`, `target`, `requested_function`,
`analysis_scope: "CATALOG"`, and either `DIRECT` or `APPROPRIATE_MEDIUM`.
`requested_function` must include at least one of `signal_type`,
`signal_family`, or `protocol_family`.

The result follows the normative result object. It contains seven layers with
separate `applicable` flags, four final result states, top-level reasons,
conditions, missing data, and `evidence`.

## Physical Connection Model v1

`DIRECT` preserves connector mating logic based on connector identity and
gender. The structured passive capability does not participate in `DIRECT`.

`APPROPRIATE_MEDIUM` is data-driven and uses exclusively
`interface.physical_connection_capabilities.passive_interconnection.status`:

- `supported` on both interfaces: physical `COMPATIBLE`;
- `unsupported` on either interface: physical `INCOMPATIBLE`;
- missing capability on either interface (`UNKNOWN`): physical
  `INSUFFICIENT_DATA`.

There is no connector allowlist. Connector equality is not required for
`APPROPRIATE_MEDIUM`. Absence remains open-world `UNKNOWN`, while
`unsupported` requires explicit catalog evidence. A physical `COMPATIBLE`
result means only that structured passive-interconnection evidence exists;
signal, protocol, direction, electrical, restrictions, and capacity layers
remain independent.

## Electrical Analyzer v1

The electrical layer is implemented for `signal_family: analog-audio` and
reads exclusively the canonical `interface.electrical_characteristics`
model. The source role uses the `output` profile and the target role uses
the `input` profile. Legacy `signal_characteristics` electrical fields are
not canonical and do not drive the decision.

An optional request-root `electrical_requirements.balance_mode` (`balanced`
or `unbalanced`) selects a single balance scenario:

```json
{
  "requested_function": {"signal_family": "analog-audio"},
  "electrical_requirements": {"balance_mode": "balanced"}
}
```

`electrical_requirements` lives only at the request root, never inside
`requested_function`. Without it, every common balance mode is evaluated
independently: any compatible selectable scenario makes the layer
`COMPATIBLE`; explicit contradictions make it `INCOMPATIBLE`; otherwise it
is `INSUFFICIENT_DATA`. Variants conditional on `balance_mode` resolve
`maximum_level` and `impedance` deterministically.

`operating_level_classes` use capability overlap (`line` into `mic,line`
is compatible; `line` into `mic`-only is incompatible). `maximum_level`,
`nominal_levels`, ordinary `impedance.nominal`/`upper_bound`, and phantom
data are informational evidence only. No 10:1 or bridging heuristic exists.
The sole normative impedance rule compares an explicitly declared source
`minimum_load_impedance` against a comparable target nominal impedance in
the same unit. Absence of required canonical data yields
`INSUFFICIENT_DATA` under open-world semantics. Phantom compatibility is
not automatically decided. Non-analog functions keep the electrical layer
non-applicable.

## Direction Layer v1

The direction layer answers whether each endpoint can perform its
functional role: the source must provide output capability and the target
must provide input capability. The canonical source is the functionally
selected signal (`selected_signal.direction`): `output` or `bidirectional`
satisfies the source role, `input` or `bidirectional` satisfies the target
role. `bidirectional` never produces a condition by itself, and missing or
ambiguous direction data yields `INSUFFICIENT_DATA`, never a guess.

`signal_characteristics.configurable_role` is legacy metadata without a
schema definition. It does not drive direction classification, its absence
means nothing, and the catalog is read as capability rather than runtime
configuration. No `CONDITIONALLY_COMPATIBLE` is produced from a configurable
role or from having several selectable modes; that state remains available
for a real structured external condition. A selectable
communication-capability assignment (`interface_assignment.mode ==
"configurable") is capability, not a condition: an allowed interface
reports its direction as compatible.

## Signal Layer v1

The signal layer answers whether both endpoints demonstrate capability for
the requested `signal_type`, `signal_family`, and `signal_format`, compared
by exact string equality with no hierarchy, alias, or cross-field inference.
Declared request constraints are conjunctive and must hold on the same
candidate signal. Each requested constraint evaluates per signal as
satisfied, explicitly contradicted, or unknown: a requested field against an
absent optional signal field (`signal_family`, `signal_format`) is unknown,
never a mismatch. A side is supported when one signal satisfies every
requested constraint, contradicted when every declared signal provably
fails at least one, and unknown otherwise. Both sides supported yields
`COMPATIBLE`; explicit contradiction on either side yields `INCOMPATIBLE`;
otherwise `INSUFFICIENT_DATA`. Without a requested format, format data is
ignored. The layer never produces `CONDITIONALLY_COMPATIBLE` and never
validates direction, protocol, or conversion: role selection stays with the
direction layer and functional identity with signal selection.

## Protocol Layer v1

The protocol layer answers whether both endpoints support the requested
`protocol_family`, compared by exact string equality with no aliases,
hierarchy, or cross-family inference (`aes67`, `ethernet`, `usb`,
`usb-2-0`, `usb-3-0`, and `usb-3-1` are all distinct). Two canonical
evidence sources are aggregated as alternatives: `signal.protocol_family`
and `communication_capabilities[*].protocol_family` honoring
`interface_assignment.allowed_interface_ids`. Any usable route without a
condition makes the side supported, even beside unrelated negative routes;
an explicitly conditional route without an unconditional one makes it
conditional; otherwise explicit impossibility on every route makes it
contradicted and incomplete data makes it unknown. In particular,
`interface_assignment.mode == "configurable"` on an allowed interface is a
valid selectable capability, never a condition by itself — only
`availability: "conditional"` (or license/module style requirements)
produces `CONDITIONALLY_COMPATIBLE`. Assignment away from the analyzed
interface, `availability: "unavailable"` with no usable alternative, an
explicitly different protocol with no unknown route, or complete catalog
coverage without the protocol all prove impossibility. The layer never
infers protocols from connectors, signal families, or Ethernet, and never
absorbs manufacturer, model, or restriction constraints.

## CLI

```text
python3 -m compatibility.analyze \
  --equipment equipment/qsys/core-8-flex.json equipment/crestron/dm-nvx-360c.json \
  --source-equipment qsys.core-8-flex --source-interface lan-a \
  --target-equipment crestron.dm-nvx-360c --target-interface ethernet-1 \
  --requested-function '{"signal_family":"ethernet"}' \
  --analysis-scope CATALOG \
  --interconnect-assumption APPROPRIATE_MEDIUM
```

Exit code `0` means the analysis executed and produced a result, including
`INCOMPATIBLE`. Exit code `2` means invalid input, missing records, or invalid
configuration.

## Conservative Limits

The implementation never infers protocols or signals from connectors,
manufacturer identity, project topology, active licenses, current
configuration, cable/adapters/converters, protocol bridges, pinouts, network
design, pool consumption, or project capacity. Undeclared required data remains
`INSUFFICIENT_DATA`.

`known_compatibilities` are collected as evidence only. They cannot override a
denied restriction or supply missing technical facts.

## Restrictions Layer v1

The restrictions layer evaluates the single `interface.connection_constraints`
object on each side, bilaterally: the source side constrains the target and
the target side constrains the source. A constraint carrying
`protocol_family` only applies when the request asks for that protocol; a
protocol-scoped constraint is ignored outside its scope. Each target
selector compares by exact equality, conjunctively across its present keys
(`equipment_id`, `manufacturer`, `model`, `product_family`,
`remote_interface_id`, `remote_interface_role`); selector lists are
alternatives (OR). A matching denied selector is an explicit contradiction
and wins over any allowed match (deny-first). `allowed_targets` restricts
only with `exhaustive: true`, and then at least one selector must match;
a non-exhaustive list never proves incompatibility. Missing selector
metadata (such as an undeclared remote interface role) yields
`INSUFFICIENT_DATA`, never a mismatch. Without constraints the layer is
not applicable. `known_compatibilities` stay evidence-only and a bare
`proprietary` flag imposes nothing by itself. The layer never produces
`CONDITIONALLY_COMPATIBLE` and never validates connector, signal,
protocol, direction, electrical, or capacity concerns.

The official DM-NVX family distinction for Dante is not represented as a fake
unavailable capability in the DM-NVX-360C record. This remains a known
`MODEL_REPRESENTATION_GAP`.

This version does not implement project modeling, cable selection, adapter or
converter selection, topology, VLAN, multicast, PTP, QoS, chassis composition,
drawing, or AI functionality.
