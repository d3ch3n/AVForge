# AVForge Generation Plan v1 Contract

Status: `PHASE_1_IMPLEMENTED`

Generation Plan is the deterministic boundary between accepted Mapping intent
and a future Equipment Candidate Builder. It does not generate equipment JSON,
choose Mapping targets, resolve conflicts, or publish catalog records.

## 1. Pipeline Boundary

```text
Fact Extraction -> Unit Normalization -> Mapping 1.1
-> Generation Plan 1.0 -> future Candidate Builder
```

Mapping targets and semantic bindings remain upstream review-owned intent.
Generation Plan records the explicit structural operations approved for future
materialization. The Candidate Builder, when implemented, will apply those
operations only.

## 2. Artifact and Identity

Generation Plan artifacts are ignored runtime data under:

```text
.ingestion/generation-plans/<job_id>.json
.ingestion/generation-plans/<job_id>.<plan_hash>.json
```

The first artifact uses the job path. A changed semantic plan receives a
content-addressed suffix; an identical rerun reuses the existing artifact.

Each plan is versioned independently:

```text
generation_plan_version: "1.0"
```

The plan binds to resolved identity, Extraction version/hash, Mapping version/
hash, Schema identity/version/hash, and vocabulary version/hash metadata.
Filesystem paths, timestamps, and display metadata are excluded from `plan_id`.

`plan_id` is derived from canonical semantic plan content. Root declarations,
entity declarations, operations, issue references/impact, and input bindings
are included.

## 3. Plan Shape

A plan contains:

- `generation_plan_version`
- `plan_id`
- `job_id`
- `input_bindings`
- `root.fields`
- `entities`
- `operations`
- `issues`
- derived `issue_impacts`
- optional provenance metadata

It does not contain a complete equipment candidate.

Root fields are explicit value sources. Required future Schema identity fields
must be declared; no defaults are invented to satisfy Schema validation.

Entity IDs are planner-owned stable IDs scoped by entity kind. They are never
derived from Fact IDs, Evidence IDs, Mapping IDs, source hashes, or array
positions.

## 4. Closed Operations

Entity declarations are represented by the authoritative `entities` collection
and are not duplicated as operations. The executable operation vocabulary is:

- `ENSURE_OBJECT`
- `SET_VALUE`
- `ADD_REFERENCE`

`DECLARE_ENTITY` is therefore represented by `entities`, preserving the accepted
semantic operation without duplicate declaration state.

Unsupported operations, executable expressions, loops, templates, JSONPath,
filesystem paths, and arbitrary code selectors are rejected.

## 5. Targets and Value Sources

Targets reuse Mapping target descriptors:

- `equipment` root
- property segments
- entity segments keyed by `local_id` or `semantic_id`
- nested entities

Array indexes, wildcards, recursive descent, and executable selectors are not
valid target identities.

`SET_VALUE` accepts only these value-source kinds:

- `literal`: accepted planner-owned JSON data.
- `fact`: Fact ID plus explicit structural path.
- `normalized_binding`: Mapping ID plus path into the accepted normalization binding.
- `identity`: one recognized resolved-identity field.
- `entity_reference`: a declared entity identity.

Fact paths never search recursively or guess property names. Missing Facts and
paths fail validation. Entity references must resolve to declared entities.

Normalized bindings are revalidated against the authoritative Mapping and Unit
Normalization rules. Generation Plan does not select new rules or perform new
conversions.

## 6. Merge and Collections

Plan validation detects knowable merge conflicts before a Builder exists:

- Identical scalar writes coalesce.
- Complementary fields on one entity are allowed.
- Contradictory scalar writes fail.
- Identical references coalesce.
- Conflicting known scalar references fail.
- Conflicting entity declarations fail.

Collection semantics default to ordered. Unordered behavior must be explicit
and local. Multiplicity is preserved. Entity collections may be serialized by
stable scoped identity where order is non-semantic. No global list sorting is
performed.

## 7. Lifecycle and Issues

Plan validity is independent from future candidate status and publication:

```text
Plan validity: VALID | INVALID
Candidate status: VALID | INCOMPLETE | INVALID (future phase)
Publication: ELIGIBLE | BLOCKED (future phase)
```

Phase 1 derives issue impact but does not implement Candidate Builder or
publication workflow. Issue impact is code-owned and cannot be overridden by
planner flags.

Supported issue codes are:

`CONFLICT`, `NOTES_ONLY`, `OMIT_UNKNOWN`, `VOCAB_GAP`, `SCHEMA_GAP`,
`INSUFFICIENT_EVIDENCE`, `VALIDATION_FAILED`, `IDENTITY_AMBIGUOUS`, and
`SOURCE_NOT_FOUND`.

Unresolved conflicts may remain in a structurally valid plan, but neither
conflicting Fact may be selected by an operation. The issue remains publication
blocking and makes a future candidate incomplete when affected structured data
is intentionally omitted.

`NOTES_ONLY` and `OMIT_UNKNOWN` create no operation by default and do not make a
future candidate incomplete. Unknown information never becomes false, zero,
null, or an unsupported value.

Vocabulary and Schema gaps, validation failure, and unresolved identity block
future execution permission. Source and evidence issues are evaluated against
the affected accepted operations rather than turning all open-world absence into
false data.

## 8. Validation Result

Phase 1 exposes structural assessment separately from strict validation:

```text
valid
errors
warnings
issue_impacts
generation_allowed
publication_blocking
```

`generation_allowed` and `publication_blocking` are derived policy outputs;
they are not alternate Plan validity states.

Structural Plan validation may be context-free. Execution authorization is
authoritative-context-dependent and fails closed: Extraction, Mapping, resolved
identity, Schema, and vocabulary contexts must be supplied and match the plan
bindings before `generation_allowed` can be true. A context-free structural
result must never be treated as execution authorization by a future Candidate
Builder.

## 9. Reruns

Generation Plan comparison returns:

- `NO_CHANGE`: same semantic plan and input bindings.
- `CHANGED`: materialization intent changed with the same inputs.
- `STALE`: authoritative input binding changed.

Semantic comparison ignores timestamps and artifact paths. Candidate generation
and publication are outside Phase 1.

## 10. Security and Scope

Plan data is passive JSON. Phase 1 supports no `eval`, `exec`, shell, dynamic
imports, executable templates, expression language, JSONPath, or embedded code.

Phase 1 does not implement:

- Candidate Builder.
- Candidate artifacts.
- Candidate status execution.
- Equipment JSON materialization.
- Publication or promotion.
- CLI generation commands.
- Schema, vocabulary, Mapping, Extraction, Normalization, or Compatibility changes.
