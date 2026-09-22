# AVForge Semantic Validator

This is the first minimal deterministic semantic-validation layer for AVForge. It validates local IDs, explicit internal references, canonical Vocabulary IDs, and explicit equipment catalog references.

Run it with one or more records:

```text
python3 validator/validate_semantics.py equipment/qsys/core-8-flex.json
python3 validator/validate_semantics.py equipment/qsys/core-8-flex.json equipment/crestron/dmf-ci-8.json equipment/crestron/dm-nvx-360c.json
python3 validator/validate_semantics.py equipment/qsys/core-8-flex.json equipment/crestron/dmf-ci-8.json equipment/crestron/dm-nvx-360c.json equipment/crestron/hd-md8x8-4kz-e.json
```

The command prints a structured JSON result and exits with code `0` when there are no errors. Unresolved references to equipment not included in the loaded catalog are warnings; invalid local references and non-canonical Vocabulary values are errors.

## Layers

- JSON Schema validation checks document structure and local types.
- Semantic validation checks canonical identity and deterministic references.
- A future Connection Engine may infer compatibility; this validator does not.

This version intentionally does not validate connector, signal, protocol, direction, or capacity compatibility; shared pools, licenses, topology, composition, and project instances are also outside its scope.

## Electrical variants

For Schema 3.6 records, the validator checks electrical variant consistency
within every interface profile. A variant condition must use a
`balance_mode` declared by the same profile, and a profile may contain at most
one variant for each balance mode. A base electrical property cannot be
repeated as a conditional property in the same profile. These checks do not
infer missing modes, require complete variant coverage, apply fallback values,
or compare impedance values for compatibility.

The validated property paths are `maximum_level`, `impedance.nominal`, and
`impedance.upper_bound`. Input and output profiles use the same rules; no
manufacturer, model, or interface-specific behavior is encoded. Missing
electrical data remains `UNKNOWN`.

## Electrical operating cases

Schema 3.10 validates neutral `power.operating_cases` references and
membership semantics. Each case must resolve `upstream.source_id` and its
source-local `mode_id`; modes are catalog identities, not runtime state.
Downstream capabilities require a non-empty scope and at least one of
voltage, current, or power. Scope references are checked against local
interface IDs, while unresolved `named_members` remain passive source
descriptions. `aggregate` and `per_member` scopes are distinct and are not
arithmetically combined.

The validator checks compatible units (`volt`/`volt-rms` for voltage,
`ampere`/`milliampere` for current, and `watt` for power), range ordering,
duplicate IDs, duplicate semantic cases, and only deterministic same-context
quantity contradictions. It does not infer PoE relationships, negotiate
runtime modes, derive wattage, execute predicates, or validate compatibility.
