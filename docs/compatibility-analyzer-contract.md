# AVForge Compatibility Analyzer Contract v1

Status: `READY_FOR_IMPLEMENTATION`
Equipment Schema dependency: `v3.7`
Vocabulary dependency: `v1.1`

## 1. Purpose and Scope

This document defines the conceptual contract for the first AVForge
Compatibility Analyzer. It is normative for the catalog analysis scope only.

The v1 question is:

> Do the available catalog data allow AVForge to state that these two
> interfaces can perform the requested function?

The analyzer evaluates a source interface, a target interface, and a requested
function together. The result does not belong to the physical interface pair
alone.

Version 1 supports `CATALOG` analysis only. It does not decide whether a
connection should be used in a project.

### 1.1 Open-World Semantics

The Compatibility Analyzer uses open-world semantics:

> Absence of evidence is not evidence of absence.

An undeclared protocol or capability does not mean that the equipment is
unsupported. When that information is necessary to decide an applicable layer,
the result is `INSUFFICIENT_DATA`.

`INCOMPATIBLE` requires sufficient contrary evidence, such as an explicit
unavailable declaration, an explicit deny, an assignment that excludes the
selected interface, an explicitly contradictory signal or protocol, an
impossible direction, or an explicitly insufficient catalog capacity.

The analyzer MUST NOT turn an incomplete catalog record into an incompatibility
without such evidence.

### 1.2 Catalog Coverage Exception

The optional Schema v3.4 field
`catalog_coverage.communication_protocols.complete` provides scoped negative
catalog evidence. It applies only when the requested function contains
`protocol_family` and only to the communication-protocol layer.

If the requested protocol is absent and this domain is `complete: true`, the
protocol is absent from the complete official catalog scope of that equipment
record and the protocol layer is `INCOMPATIBLE`. This does not assert universal
or permanent product non-support. It does not cover another model, variant,
firmware state, installed module, or protocol outside the cataloged scope.

If coverage is absent, `communication_protocols` is absent, or `complete` is
`false`, an absent requested protocol remains `INSUFFICIENT_DATA`.

When the requested protocol is explicitly present, the analyzer evaluates its
capability, interface assignment, availability, and restrictions normally;
coverage does not override that analysis. Coverage is not relevant when no
`protocol_family` is requested and does not participate in any other layer.

## 2. Input Contract

The conceptual input MUST contain:

- `source`
- `target`
- `requested_function`
- `analysis_scope`
- `interconnect_assumption`

`source` and `target` MUST contain:

```json
{
  "equipment_id": "qsys.core-8-flex",
  "interface_id": "lan-a"
}
```

`equipment_id` identifies the catalog record. `interface_id` identifies the
specific interface in that record. An aggregated quantity is not a substitute
for an individual interface ID.

### 2.1 Requested Function

`requested_function` MUST be an object containing at least one of:

- `signal_type`
- `signal_family`
- `protocol_family`

It MAY additionally contain:

- `signal_format`
- `direction`
- `capacity_requirement`

These fields are requirements for the analysis, not merely search filters.

`signal_type` is a broad category such as network, audio, video, control, or
data. `signal_family` is a technical family such as Ethernet, analog-audio,
AES3, or HDBaseT. `protocol_family` identifies a specific protocol or
ecosystem. Existing canonical IDs and documented values MUST be used; the
analyzer MUST NOT invent values to complete a request.

`signal_format` refines the requested signal when applicable. `direction`
states a required source/target direction or functional role. Neither field
is required when the catalog data and the requested function do not need that
refinement.

`capacity_requirement` is optional. Its presence activates the capacity layer
and expresses a quantitative or other explicit capacity requirement, such as
`rx_channels: 8`.

The analyzer MUST reject or report insufficient data for a request that has no
usable function discriminator. It MUST NOT silently downgrade such a request
to an unqualified connector comparison.

### 2.2 Analysis Scope

Version 1 accepts only:

```json
"analysis_scope": "CATALOG"
```

`CATALOG` asks whether the published equipment records contain enough
information to establish compatibility. It does not include installed state,
current allocation, or project configuration.

`PROJECT` is a future scope and is not implemented or modeled by this
contract.

### 2.3 Interconnect Assumption

The input MUST explicitly state one of:

- `DIRECT`
- `APPROPRIATE_MEDIUM`

`DIRECT` means the source and target physical interfaces must mate directly.
Connector gender and mating rules therefore participate in the physical
analysis.

`APPROPRIATE_MEDIUM` means the interfaces may be joined by a passive,
technically justified medium, normally a suitable cable and its standard
terminations. It does not assume the existence of an adapter, converter,
scaler, active transceiver, protocol bridge, signal transformation, or other
active device.

An appropriate passive medium MUST NOT turn HDMI into DisplayPort, or any
other non-equivalent signal or protocol family, merely because commercial
converters exist. A different connector may be accepted under this assumption
only when a passive interconnect and compatible endpoint behavior are
technically justified by the available data. If that cannot be established,
the physical layer is `INSUFFICIENT_DATA` or `INCOMPATIBLE`, as applicable.

The v1 contract does not create a cable catalog.

Physical Connection Model v1 governs `APPROPRIATE_MEDIUM` exclusively
through the structured catalog capability
`interface.physical_connection_capabilities.passive_interconnection.status`:

- `supported` on source and target: physical `COMPATIBLE`;
- `unsupported` on either side: physical `INCOMPATIBLE`;
- missing capability on either side (`UNKNOWN`): physical
  `INSUFFICIENT_DATA`.

There is no connector allowlist. Connector equality is not required for
`APPROPRIATE_MEDIUM`. A physical `COMPATIBLE` result establishes only
structured passive-interconnection evidence; it does not establish final
compatibility.

### 2.4 Capability Assignment

`allowed_interface_ids` identifies the interfaces to which a capability may be
assigned.

With `mode: "fixed"`, the capability is bound to the declared interface(s).
An interface outside the declared list is incompatible with that capability.

With `mode: "configurable"`, the capability may be assigned to one of the
declared interfaces according to the documented product behavior. When the
selected interface is allowed but configuration or assignment is required,
the layer is `CONDITIONALLY_COMPATIBLE`.

A documented default interface does not imply a fixed assignment. In
particular, a default Audio/NAX port remains configurable when the catalog
documents other allowed ports.

## 3. Final Results

The final result MUST be exactly one of these four values:

### `COMPATIBLE`

All applicable and necessary requirements are satisfied by known catalog data,
with no unresolved condition or required missing information.

### `INCOMPATIBLE`

At least one applicable requirement is explicitly contradicted. Examples
include an incompatible signal family, incompatible protocol, incompatible
direction, insufficient declared catalog capacity, or an explicit denied
restriction.

### `CONDITIONALLY_COMPATIBLE`

The applicable technical requirements are compatible, but a known and
explicit condition must be satisfied. A condition is not a replacement for
missing information.

### `INSUFFICIENT_DATA`

At least one applicable layer requires information that is absent or
unresolved, and the available data do not establish compatibility. Missing
data in a non-applicable layer do not produce this result.

`NOT_APPLICABLE` is not a final result.

## 4. Layer Contract

The analyzer MUST evaluate these seven layers when relevant:

- `physical`
- `electrical`
- `signal`
- `protocol`
- `direction`
- `restrictions`
- `capacity`

Each layer MUST have this conceptual shape:

```json
{
  "applicable": true,
  "result": "COMPATIBLE",
  "reasons": []
}
```

When `applicable` is `true`, `result` is required and MUST be one of the four
final result values. When `applicable` is `false`, `result` MUST be omitted.
The layer does not participate in final aggregation.

Applicability is determined by the requested function and the connection
assumption. It is not a claim that the equipment lacks the corresponding
technical property.

### 4.1 Layer Responsibilities

`physical` evaluates the selected interconnect assumption. Under `DIRECT`
it evaluates connector identity and physical mating. Under
`APPROPRIATE_MEDIUM` it evaluates only the structured passive-interconnection
capability described above; connector identity remains available as context
but does not decide that assumption.

`electrical` evaluates electrical requirements relevant to the requested
function, including levels, impedance, balance, power, and electrical limits.
Analog electrical data are not required for a network protocol analysis unless
the requested function explicitly requires them.

`signal` evaluates signal type, family, format, channels, and related signal
characteristics.

`protocol` evaluates the requested protocol family, its declared support, and
the capability-to-interface assignment. A connector or generic signal family
does not imply protocol support.

`direction` evaluates source/target roles, input/output direction,
bidirectionality, and any required mode selection.

`restrictions` evaluates explicit allowed and denied targets, roles,
protocols, licenses, firmware, modules, and other documented restrictions.
When no restriction is relevant to the requested function, this layer is
non-applicable.

`capacity` is applicable only when `requested_function` includes
`capacity_requirement`. In `CATALOG`, it evaluates declared catalog capacity
only. Capability existence is not the same as sufficient catalog capacity.

## 5. Missing Data and Conditions

Missing data affect the final result only when all of the following are true:

1. The layer is applicable.
2. The missing information is necessary to decide that layer.
3. No already-proven incompatibility in another applicable layer determines
   the final result first.

Missing information in a non-applicable layer MUST be ignored during
aggregation. Unknown is not a condition.

`CONDITIONALLY_COMPATIBLE` requires an explicit known condition, such as:

- selecting input or output mode;
- assigning a capability to a particular interface;
- activating a documented license;
- applying a known capacity modifier;
- applying a required configuration;
- using a documented balanced/unbalanced connection.

## 6. Restrictions and Evidence

An explicit denied restriction has precedence over generic compatibility:

```text
explicit denied restriction -> INCOMPATIBLE
```

This remains true even when connector, signal, or generic protocol data agree,
or when positive generic compatibility evidence exists.

An allowed restriction satisfies only that restriction. It does not prove
complete physical, electrical, signal, protocol, direction, or capacity
compatibility.

`known_compatibility` is evidence, not an independent technical layer. It may
reinforce a conclusion, record a known condition, or resolve a limited doubt
when its scope and technical basis match the requested function. It MUST NOT:

- override an explicit deny;
- invent protocol support;
- replace required technical data;
- turn generic compatibility into specific compatibility.

## 7. Normative Result Object

The conceptual result object is:

```json
{
  "source": {
    "equipment_id": "qsys.core-8-flex",
    "interface_id": "lan-a"
  },
  "target": {
    "equipment_id": "crestron.dm-nvx-360c",
    "interface_id": "ethernet-1"
  },
  "requested_function": {
    "signal_family": "ethernet",
    "protocol_family": "aes67"
  },
  "analysis_scope": "CATALOG",
  "interconnect_assumption": "APPROPRIATE_MEDIUM",
  "result": "CONDITIONALLY_COMPATIBLE",
  "layers": {
    "physical": { "applicable": true, "result": "COMPATIBLE" },
    "electrical": { "applicable": false },
    "signal": { "applicable": true, "result": "COMPATIBLE" },
    "protocol": { "applicable": true, "result": "COMPATIBLE" },
    "direction": { "applicable": true, "result": "COMPATIBLE" },
    "restrictions": { "applicable": false },
    "capacity": { "applicable": false }
  },
  "reasons": [],
  "conditions": [],
  "missing_data": [],
  "evidence": []
}
```

This object is conceptual. Version 1 does not create a JSON Schema for it.

## 8. Final Aggregation

Only layers with `applicable: true` participate. Precedence is:

```text
INCOMPATIBLE
  > INSUFFICIENT_DATA
  > CONDITIONALLY_COMPATIBLE
  > COMPATIBLE
```

The rules are:

1. Any applicable layer with `INCOMPATIBLE` produces final `INCOMPATIBLE`.
2. Otherwise, any applicable layer with `INSUFFICIENT_DATA` produces final
   `INSUFFICIENT_DATA`.
3. Otherwise, any applicable layer with `CONDITIONALLY_COMPATIBLE` produces
   final `CONDITIONALLY_COMPATIBLE`.
4. Otherwise, all applicable layers are `COMPATIBLE` and the final result is
   `COMPATIBLE`.

Therefore, a known condition combined with another required but unknown fact
produces `INSUFFICIENT_DATA`.

## 9. Compatibility Analysis versus Project Connection

Compatibility Analysis is not a Project Connection Decision.

`CATALOG` compatibility answers:

> Can the interfaces technically perform the requested function according to
> the available catalog data?

A future project decision will answer:

> Should this connection be used in this project, and in which way?

The future project layer may consider topology, routing, available capacity,
redundancy, installed licenses, configuration, VLAN, multicast, PTP, QoS,
slot/module occupancy, and project design rules. None of these are evaluated
by this v1 contract.

## 10. Normative Cases CA1-CA20

| Case | Scenario | Expected result |
|---|---|---|
| CA1 | All applicable layers are compatible | `COMPATIBLE` |
| CA2 | Same connector, incompatible signal family | `INCOMPATIBLE` |
| CA3 | Explicitly incompatible protocol | `INCOMPATIBLE` |
| CA4 | Incompatible direction | `INCOMPATIBLE` |
| CA5 | Explicit denied restriction | `INCOMPATIBLE` |
| CA6 | Positive generic evidence conflicts with denied restriction | `INCOMPATIBLE` |
| CA7 | Known output-mode selection is required | `CONDITIONALLY_COMPATIBLE` |
| CA8 | Required license condition is explicitly known | `CONDITIONALLY_COMPATIBLE` |
| CA9 | Required data is missing in an applicable layer | `INSUFFICIENT_DATA` |
| CA10 | Analog electrical data missing for network protocol analysis | Missing data ignored; not `INSUFFICIENT_DATA` |
| CA11 | Known condition plus another required missing fact | `INSUFFICIENT_DATA` |
| CA12 | No capacity requirement in requested function | `capacity.applicable = false` |
| CA13 | Requested capacity is met by catalog declaration | Capacity `COMPATIBLE` |
| CA14 | Requested capacity exceeds declared catalog capacity | `INCOMPATIBLE` |
| CA15 | Requested capacity exists but maximum is undocumented | `INSUFFICIENT_DATA` |
| CA16 | HDMI female/female under `DIRECT` | Physical `INCOMPATIBLE` |
| CA17 | HDMI female/female under `APPROPRIATE_MEDIUM` | Physical `COMPATIBLE` |
| CA18 | HDMI/DisplayPort relying on an implicit converter | `INCOMPATIBLE`; the selected assumption excludes converters |
| CA19 | Protocol capability exists but is not assigned to the selected interface | `INSUFFICIENT_DATA`; an explicit negative assignment would instead be `INCOMPATIBLE` |
| CA20 | Applicable layers compatible and irrelevant data missing elsewhere | `COMPATIBLE` |

## 11. Real Equipment Examples

### 11.1 Core 8 Flex LAN A to DM-NVX-360C Ethernet

The result changes with `requested_function`; it is not a permanent property
of the physical pair.

| Requested function | Applicable layers | Expected result |
|---|---|---|
| Generic Ethernet | physical, signal, direction | `COMPATIBLE` under an appropriate passive medium |
| AES67 | physical, signal, protocol, direction | `CONDITIONALLY_COMPATIBLE` for Ethernet 1 when both records allow AES67 and assignment is configurable |
| Dante | physical, signal, protocol | `INSUFFICIENT_DATA` when the Core declares Dante but the DM-NVX-360C has neither Dante nor an explicit deny |
| Q-LAN | physical, signal, protocol | `INSUFFICIENT_DATA` when the Core declares Q-LAN but the DM-NVX-360C has neither Q-LAN nor an explicit deny |
| DM NVX | physical, signal, protocol | `INSUFFICIENT_DATA` when the DM-NVX-360C declares DM NVX but the Core has neither DM NVX nor an explicit deny |
| Generic control | physical, signal, protocol, direction | `INSUFFICIENT_DATA` when no common control protocol is identified |

Port 3 is the documented Audio/NAX default, not an exclusive assignment.
Analog impedance and voltage data are irrelevant and do not make
`electrical.applicable` true for these network analyses.

### 11.2 Core Flex Channel to DM-NVX-360C Analog Audio I/O

For an analog audio request, `physical`, `electrical`, `signal`, and
`direction` are applicable. `protocol` is non-applicable. `restrictions` is
applicable only when a restriction is declared, and `capacity` is applicable
only when a quantity is requested.

The result is `COMPATIBLE` only when connector/interconnect details, electrical
characteristics, signal format, and complementary direction are established.
Known mode selection or a documented balanced/unbalanced wiring requirement
produces `CONDITIONALLY_COMPATIBLE`. Missing required pinout or electrical
data produces `INSUFFICIENT_DATA`, not a condition.

## 12. Gap Classification

### Analyzer Contract Requirements

These are contract concepts, not Equipment Schema gaps:

- `requested_function`;
- `analysis_scope`;
- `interconnect_assumption`;
- layer `applicable` flags;
- final and layer result states;
- aggregation rules;
- `evidence`.

### Equipment Model Gaps

Potential future data-model needs include structured pinout, connector mating
rules, cable/interconnect records, and more precise protocol-to-interface
assignments. These are not required changes for this contract v1.

### Vocabulary Gaps

Future controlled values may be needed for compatibility relation semantics,
proprietary pairing, and detailed passive interconnect types. No new
Vocabulary ID is introduced by this contract.

### Semantic Rule Gaps

Implementation will need deterministic rules for applicability, layer
comparison, bidirectional behavior, capability assignment, missing data,
conditions, restrictions, and catalog capacity.

### Project Model Gaps

Future project analysis requires installed state, resource allocation,
topology, routing, license state, VLAN, multicast, PTP, QoS, redundancy,
occupancy, and design rules.

The official DM-NVX family documentation distinguishes Dante support by model:
Dante applies to DM-NVX-363 and DM-NVX-363C, not DM-NVX-360 or DM-NVX-360C.
The current Equipment Schema has an `availability` value of `unavailable`,
but no clean standalone representation for an unsupported protocol without
creating an artificial capability and assignment. This is a
`MODEL_REPRESENTATION_GAP`; the analyzer MUST NOT create a fake Dante
capability in the DM-NVX-360C record.

## 13. Historical Scenarios and Executable Regressions

Labels such as `SV1-SV20`, `MC1-MC20`, and `UM1-UM20` refer to historical or
conceptual validation scenarios. They are not executable test suites in the
current repository unless corresponding test files are present.

The executable v0.1 regressions are JSON parsing, Draft 2020-12 validation,
Semantic Validator execution, and `compatibility/test_analyze.py`.

## 14. Layered System Responsibilities

- **JSON Schema**: structural validity, types, required fields, and local formats.
- **Semantic Validator**: local identity, references, canonical Vocabulary IDs,
  and catalog reference integrity.
- **Compatibility Analyzer**: technical compatibility reasoning for a requested
  function.
- **Future Project Engine**: project-specific connection and design decisions.
- **Future Drawing Engine**: graphical representation.

These responsibilities MUST remain separate. The Semantic Validator is an
independent prerequisite for valid catalog input; it is not a compatibility
engine.

## 15. Contract Decision

The v1 contract is ready for implementation of a conservative `CATALOG`
analyzer. No change is required in Equipment Schema v3.3 or Vocabulary v1.1
to document or implement this contract. The analyzer must report
`INSUFFICIENT_DATA` rather than infer undocumented cables, converters,
protocols, pinouts, project availability, or proprietary compatibility.

**Compatibility Analyzer Contract v1: `READY_FOR_IMPLEMENTATION`**
