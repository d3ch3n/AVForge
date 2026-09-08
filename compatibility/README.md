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

The official DM-NVX family distinction for Dante is not represented as a fake
unavailable capability in the DM-NVX-360C record. This remains a known
`MODEL_REPRESENTATION_GAP`.

This version does not implement project modeling, cable selection, adapter or
converter selection, topology, VLAN, multicast, PTP, QoS, chassis composition,
drawing, or AI functionality.
