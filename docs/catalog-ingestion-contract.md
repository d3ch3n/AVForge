# AVForge Catalog Ingestion Contract v1.0

Status: `ARCHITECTURE_REVIEW`

This document defines the contract for a future AVForge Catalog Ingestion
Framework. It defines job inputs, intermediate evidence, decisions, review
boundaries, and publication safeguards. It does not implement ingestion,
source scraping, agents, databases, schema changes, vocabulary changes, or
Compatibility Analyzer behavior.

## 1. Scope and Principles

The framework converts an equipment request into an auditable draft candidate.
It does not turn a web page directly into an equipment record. Every
structured fact must pass through identity resolution, source classification,
fact normalization, mapping, and deterministic validation.

The framework preserves these AVForge principles:

- The equipment model remains manufacturer- and category-neutral.
- A physical connector is not a signal, protocol, or compatibility claim.
- A connector never implies a protocol or signal family.
- Proprietary interfaces require explicit protocol/family evidence and pairing
  restrictions when applicable.
- Physical endpoints are distinct from logical capabilities and runtime
  resources.
- Stable IDs identify equipment, interfaces, signals, capabilities, pools,
  connectors, points, and relations.
- Official manufacturer evidence is separate from `internal_knowledge`.
- Absence is `UNKNOWN` by default, not a negative fact.
- Open-world Compatibility Analyzer semantics remain unchanged.
- Conflicting official sources are preserved and are not silently reconciled.
- A source qualifier such as `>`, `<`, `approximately`, `range`, `NR`, or
  `conditional` must not be converted into false precision.
- A schema gap and a vocabulary gap are different decisions.
- Current schema, semantic validator, vocabulary checks, and Compatibility
  Analyzer are authoritative components, not targets to be changed to make a
  draft pass.
- Conditional, licensed, firmware-dependent, modular, and runtime behavior is
  never flattened into unconditional hardware capability.
- `draft` is a catalog status, not approval for publication.

The framework has two separate products:

1. A job result containing resolved identity, sources, facts, issues, proposed
   mapping, validations, and a decision.
2. A candidate `equipment/<manufacturer>/<model>.json` file, created only when
   the job has enough approved information to generate one.

The job evidence remains the authority for why a candidate contains, omits, or
describes a fact. The equipment record remains the current AVForge catalog
artifact and must conform to the current schema.

## 2. Non-Goals and Boundaries

Version 1 does not:

- ingest NVM-302E;
- modify `schemas/equipment.schema.json`;
- modify `validator/validate_semantics.py`;
- modify `compatibility/analyze.py` or its result contract;
- add vocabulary IDs automatically;
- publish, commit, or push automatically;
- infer compatibility from connector equality;
- calculate effective capacity for a configured instance;
- decide project wiring or deployment safety;
- treat an LLM response as validation;
- permanently store arbitrary source binaries in the Git repository.

The framework may identify a schema or vocabulary gap, but that issue is
escalated to the appropriate architecture or vocabulary process. Ingestion
does not solve the gap by adding an ad hoc field or identifier.

## 3. End-to-End Pipeline

Each stage consumes a defined artifact and emits a defined artifact. A stage
may add evidence or issues, but must not erase unresolved uncertainty.

| Stage | Input | Output | Responsibility | Must not do | Failure modes |
| --- | --- | --- | --- | --- | --- |
| Intake | User list and optional hints | Intake items with stable job keys | Parse and validate the small user request | Require technical specifications or silently repair identity | `INVALID_INTAKE`, `DUPLICATE_ITEM` |
| Identity Resolution | Intake item and discovery candidates | One resolved identity or an ambiguity set | Establish exact manufacturer/model/variant scope before facts merge | Merge similar models, bundles, revisions, or licenses | `IDENTITY_AMBIGUOUS`, `IDENTITY_NOT_FOUND` |
| Source Discovery | Resolved identity | Candidate source manifest | Find manufacturer-domain and approved supporting sources | Make search snippets canonical; extract facts as proof of discovery | `SOURCE_NOT_FOUND`, `IDENTITY_SCOPE_MISMATCH` |
| Source Acquisition | Source manifest | Immutable acquired-source metadata and artifacts | Retrieve HTML/PDF/text and record hash/retrieval metadata | Treat redirects, mirrors, or changed content as the same source without recording it | `ACQUISITION_FAILED`, `UNSUPPORTED_FORMAT`, `CONTENT_CHANGED` |
| Source Classification | Acquired sources | Classified source manifest | Assign tier, document type, revision, scope, and canonicality | Upgrade a reseller or snippet to official evidence | `SOURCE_UNVERIFIED`, `REVISION_UNKNOWN` |
| Fact Extraction | Classified sources | Raw fact candidates with locators | Extract explicit claims without interpretation beyond local wording | Invent values, units, conditions, or negatives | `EXTRACTION_UNREADABLE`, `EVIDENCE_MISSING` |
| Evidence Normalization | Raw fact candidates | Normalized fact ledger | Normalize terminology, units, qualifiers, and conditions while retaining source wording | Remove qualifiers or silently convert bounds/ranges | `NORMALIZATION_AMBIGUOUS`, `UNIT_UNKNOWN` |
| Conflict Detection | Normalized fact ledger | Conflict set and reconciled fact candidates | Compare same-scope claims and classify relationships | Pick newest/largest/smallest by default | `TRUE_CONFLICT`, `UNKNOWN_RELATIONSHIP` |
| Schema/Vocabulary Mapping | Resolved facts, current schema/vocabularies | Mapping decisions and draft field plan | Select faithful structured fields, notes, omission, or gap issue | Shoe facts into unrelated fields or add vocabulary silently | `VOCAB_GAP`, `SCHEMA_GAP`, `MAPPING_CONFLICT` |
| Draft Generation | Approved mapping plan and identity | Candidate equipment JSON | Generate deterministic JSON using current conventions | Generate unsupported IDs, fields, protocols, or compatibility claims | `DRAFT_GENERATION_FAILED` |
| Structural Validation | Candidate JSON and current schema | Structural validation result | Run JSON parse and JSON Schema validation | Redefine schema pass criteria | `JSON_INVALID`, `SCHEMA_INVALID` |
| Semantic Validation | Candidate JSON and catalog/vocabularies | Semantic validation result | Invoke the repository semantic validator | Replace or weaken validator rules | `SEMANTIC_INVALID`, `REFERENCE_WARNING` |
| Regression Validation | Candidate and existing test/catalog inputs | Test, analyzer, and catalog results | Run relevant tests, analyzer regressions, and full catalog validation | Treat a missing test as proof of correctness | `TEST_FAILED`, `ANALYZER_REGRESSION`, `CATALOG_INVALID` |
| Machine Audit | Candidate and all validation artifacts | Deterministic audit report | Check counts, IDs, paths, omitted NR/unknown semantics, and forbidden patterns | Use a manually reconstructed summary as evidence | `AUDIT_FAILED`, `EXPECTED_STRUCTURE_MISMATCH` |
| Decision / Review Queue | All stage outputs | Primary state plus issue list | Aggregate deterministic gates and route exceptions to a human | Hide conflicts or use a subjective score as final state | Any blocking issue state |
| Publication | Explicit approval and clean repository state | Explicit publication proposal or approved publication | Stage only approved files after a separate human action | Commit or push as a side effect of ingestion | `PUBLICATION_BLOCKED` |

Stages are independently resumable. A failed item does not abort unrelated
items in the same batch.

## 4. Intake Contract

The canonical intake representation is a small JSON document. CSV is an input
convenience that maps one row to one `items[]` element; it is not a second
semantic contract.

```json
{
  "contract_version": "1.0",
  "items": [
    {
      "manufacturer": "Q-SYS",
      "model": "NVM-302E",
      "product_family": null,
      "official_url": null,
      "local_sources": [],
      "notes": null
    }
  ]
}
```

Required for normal automated ingestion per item:

- `manufacturer`: non-empty user-supplied string;
- `model`: non-empty user-supplied string.

Optional per item:

- `product_family`;
- `official_url`;
- `local_sources`: paths supplied by the user;
- `notes`.

The normal automated input is manufacturer plus model, for example
`Q-SYS,NVM-302E`. A legacy model-only value in a CSV `equipment` column may
still be parsed for compatibility, but it is marked unresolved and cannot
enter automated source discovery until a manufacturer is supplied or manually
resolved. The supplied manufacturer is a search and identity constraint, not
proof that a discovered source is official.

An intake item receives a deterministic `job_key` derived from its normalized
logical intake content, not its position in a batch. The job record also
retains `batch_index` as occurrence metadata. Reordering a CSV therefore does
not change the logical job key, while a duplicate logical item is still
rejected within one batch. The job key is not an equipment ID and must not be
used as a catalog ID.

Intake validation rejects empty models, malformed JSON/CSV, duplicate exact
items in one batch, and unsupported fields. Missing manufacturer is retained
only as an explicit unresolved/manual path; it is not valid normal automated
ingestion. The
same logical item in a later batch receives the same job key and can be
compared for rerun; occurrence metadata does not create a new logical job.

## 5. Identity Resolution

Identity resolution precedes source merging and fact extraction. A resolved
identity contains:

```json
{
  "manufacturer": "Q-SYS",
  "canonical_model": "NVM-302E",
  "product_family": "NVM Series",
  "variant": null,
  "region": null,
  "hardware_revision": null,
  "generation": null,
  "identity_evidence": ["source-id:locator"],
  "identity_status": "RESOLVED"
}
```

The resolver must distinguish:

- model from product family;
- hardware SKU from bundle or accessory SKU;
- hardware from license SKU;
- regional suffix from a different hardware variant;
- revision/generation from a new product;
- base product from an installed module or application;
- identical names with different manufacturer ownership.

A source can support identity only when its title, model label, part number,
product page, or equivalent evidence matches the requested scope. Technical
facts from a source outside the resolved scope remain unmerged evidence and
produce `IDENTITY_SCOPE_MISMATCH`.

Resolution is `IDENTITY_AMBIGUOUS` when two or more plausible identities remain
and available evidence cannot deterministically distinguish them. The resolver
must not select a likely variant merely because it has more documentation.

Resolution is `NEEDS_REVIEW` through the issue `IDENTITY_AMBIGUOUS` when:

- a regional, revision, bundle, license, or hardware-module distinction could
  change technical facts;
- two official product pages map the name to different products;
- a source identifies only a family, not the exact model;
- the requested model is discontinued or renamed and equivalence is not
  explicitly documented.

Only facts after identity resolution may enter the canonical fact ledger.

## 6. Manufacturer Trust and Source Discovery

AVForge uses a small tracked manufacturer registry containing only canonical
manufacturer identity, explicitly approved aliases, verified official web
roots, approved document hosts, and trust provenance. It contains no equipment
models or technical facts. A `VERIFIED` registry entry is reusable across
equipment jobs for that manufacturer. A new domain discovered from the web
creates a `PROPOSED` trust decision and requires explicit review before it can
be promoted to `VERIFIED`; discovery never writes permanent trust silently.

Known manufacturers use their verified roots to scope discovery. Unknown
manufacturers use the supplied manufacturer plus model to generate bootstrap
queries, but provider ranking and provider trust assertions remain discovery
metadata only. Official authority is established by AVForge registry/trust
evaluation and acquired manufacturer-controlled evidence. The supplied
manufacturer must still match acquired page/document identity evidence.

Web search locates candidates. Manufacturer-controlled sources provide
canonical evidence. Resellers, distributors, forums, mirrors, community pages,
and snippets remain noncanonical discovery or corroboration sources.

## 7. Source Discovery and Classification

Every source candidate has a manufacturer-domain verification result. An
official claim requires a verified registry root or a source that verified
manufacturer-controlled evidence explicitly links or redirects to. A URL,
search ranking, snippet, or provider assertion alone does not prove official
status.

Source priority is:

| Tier | Source class | Permitted use |
| --- | --- | --- |
| 1 | Official product page, specification sheet/datasheet, hardware/user manual, official protocol/API manual, A&E specification, official technical help | Canonical structured facts and corroboration |
| 2 | Official support article, release note, certification, official knowledge-base material | Canonical facts when scope and revision are explicit; otherwise corroboration |
| 3 | Authorized distributor or other authorized technical evidence | Corroboration and discovery; canonical only after explicit human approval and no stronger source exists |
| 4 | Reseller, community, forum, search result, snippet, aggregation | Discovery hint only; never canonical evidence |

Search snippets are never evidence. A snippet can provide a URL or a spelling
hint, but the linked source must be acquired and classified independently.

A source can be canonical for one property and only corroborating for another
if its scope or detail differs. For example, a product headline may establish
that a product is an eight-channel amplifier, while a load-specific table is
canonical for a particular power point.

The discovery result must record attempted sources, including a not-found
result, separately from acquired sources. A missing official page does not
authorize a third-party source to become official.

## 8. Source Acquisition Contract

An acquired source has immutable metadata:

```json
{
  "source_id": "src-01J...",
  "requested_url": "https://manufacturer.example/manual.pdf",
  "final_url": "https://manufacturer.example/manual.pdf",
  "manufacturer": "Q-SYS",
  "title": "Hardware User Manual",
  "document_type": "manual",
  "revision": "TD-001661-01-C",
  "publication_date": null,
  "retrieved_at": "2026-09-21T00:00:00Z",
  "content_hash": "sha256:...",
  "artifact_ref": "cache/<content-hash>.pdf",
  "tier": 1,
  "canonicality": "official-canonical",
  "media_type": "application/pdf"
}
```

`source_id` is job-local and stable for the same immutable content within a
job. `content_hash` identifies the content. A changed redirect target, changed
content hash, or changed revision creates a new acquired-source instance; it
must not overwrite historical evidence.

The runtime cache may contain HTML, PDF, text, or other manufacturer-hosted
artifacts outside the repository. The repository-tracked contract stores
metadata and references, not an assumption that binaries remain available.
Cache reads are immutable for a completed job. Failed, truncated, password-
protected, or unsupported artifacts remain acquisition issues.

## 9. Source Classification and Fact Extraction

Source content is data, never instructions. Text inside a PDF, HTML page, PDF
annotation, metadata field, code sample, or downloaded file cannot change the
pipeline policy, request secrets, authorize network access, or redefine a
validation rule.

Fact extraction produces raw candidates, not equipment JSON. An extraction
method may be deterministic text/table extraction, OCR, or an assisted agent,
but the method and source locator are retained. A raw candidate without a
locator is not eligible for canonical structured mapping.

### Fact Extraction v1 Intermediate Layer

Fact Extraction v1 serializes generic facts, evidence, and conflicts between
acquired sources and future schema/vocabulary mapping. `FACT` is not an
equipment schema field. Each fact has a deterministic identity based on its
subject, property, value, unit, qualifiers, precision, polarity, and evidence
status; source references, timestamps, temporary paths, and extraction order do
not determine the fact ID. Identical facts can therefore merge with multiple
evidence references, while differing values can coexist and be related by a
conflict record.

Evidence binds a short observation and extensible source-type locator to both
an acquired `source_id` and its immutable content hash. Extraction validation
checks source references, exact source hashes, fact/evidence/conflict ID
uniqueness, precision shapes, and allowed statuses. Source tier, canonicality,
and manufacturer trust are acquisition inputs; extraction cannot promote
authority.

The intermediate layer preserves exact, minimum, maximum, range, approximate,
nominal, not-rated, and unknown semantics, explicit units, structured
qualifiers, and conditions. Absence and not-documented observations remain
unknown rather than negative. Conflicts retain their relationship and review
status without automatically selecting a winner. Reruns ignore observation
timestamps and distinguish evidence changes from fact and conflict changes.

Source content remains passive data and cannot execute instructions or change
trust, schema, vocabulary, repository, or publication state. Extraction
results are runtime artifacts under `.ingestion/extractions/`; equipment JSON
generation and schema mapping are later stages.

Extraction must preserve the local wording and qualifiers. It must not:

- turn a headline into a detailed operating point;
- infer a protocol from an Ethernet or RJ45 connector;
- infer a signal family from a connector;
- infer a negative capability from omission;
- infer a per-port value from a shared budget;
- use a later or earlier model's table for the resolved model;
- convert an application, license, firmware, or mode statement into base
  hardware support.

## 10. Minimum Fact Ledger

The fact ledger is the smallest intermediate representation that makes mapping
auditable. It is not a universal ontology and does not need every possible
engineering property.

```json
{
  "fact_id": "fact-00042",
  "subject": { "kind": "interface", "local_id": "output-a" },
  "property": "maximum_power",
  "value": 800,
  "unit": "watt",
  "qualifiers": {
    "topology": "independent",
    "load": { "type": "low_impedance", "impedance": 2, "unit": "ohm" }
  },
  "conditions": [],
  "semantic_precision": "exact",
  "polarity": "POSITIVE_EXPLICIT",
  "evidence_refs": ["ev-00042"],
  "extraction_method": "table-text",
  "evidence_status": "SUPPORTED",
  "mapping_status": "PENDING"
}
```

Required ledger fields are `fact_id`, `subject`, `property`, `value` or an
explicit unknown marker, `qualifiers`, `conditions`, `evidence_refs`,
`extraction_method`, and `evidence_status`. `unit` is required for a measured
numeric value and absent for a non-measurement.

`subject` can refer to the resolved equipment, an interface, signal,
physical connector, connection point, communication capability, power source,
or catalog capability. A subject must be resolved before it is mapped. A
fact about a logical capability cannot be attached to a physical connector
merely because the source presents them near each other.

Facts with `value` unavailable use `evidence_status: UNKNOWN` and retain the
reason in `notes`; they are not emitted into an unrelated structured field.

An absent-value fact with `semantic_precision: unknown` or `not-rated`, or with
polarity `UNKNOWN` or `NOT_APPLICABLE`, must not contain `value` or `unit`.
`range` requires numeric `minimum` and `maximum` bounds with minimum less than
or equal to maximum. `minimum` and `maximum` require one numeric value.

## 11. Provenance and Evidence

An evidence record links a fact to one acquired source:

```json
{
  "evidence_id": "ev-00042",
  "source_id": "src-01J...",
  "locator": {
    "kind": "pdf",
    "page": 19,
    "section": "Power Specifications - 8-Channel Models",
    "table": "Configuration Loads",
    "row": "Independent Channels, 2 ohm"
  },
  "normalized_locator": "pdf:p19#power-specifications-8-channel-models:independent:2-ohm",
  "snippet": "800 W max; 300 W continuous",
  "evidence_role": "primary",
  "observed_at": "2026-09-21T00:00:00Z"
}
```

PDF locators should include page and section; table and row are included when
available. HTML locators include final URL, heading/section, and a stable
fragment or short quote when available. A short snippet is optional and must
not be treated as a substitute for the source artifact or locator.

Multiple sources support one fact by multiple `evidence_refs`. The ledger must
retain which sources independently support it. One source may support a fact
while another conflicts with it; both remain attached to the conflict.

The generated equipment record's `documentation[]` contains the source
references relevant to the record. Full fact/evidence ledgers belong to the
job artifacts and review report; the record does not need to contain a
copyrighted excerpt or the entire extraction trace.

## 12. Evidence Status and Open World

The following polarity values are normative:

| Polarity | Meaning | Structured result |
| --- | --- | --- |
| `POSITIVE_EXPLICIT` | The source explicitly documents support/presence | May map to a positive fact if scope matches |
| `NEGATIVE_EXPLICIT` | The source explicitly documents absence, exclusion, unavailable, or not supported | May map to a negative fact only in a suitable schema field and scope |
| `UNKNOWN` | The source does not establish the property | Omit or use a schema-defined unknown representation; never false |
| `NOT_APPLICABLE` | The property does not apply to the resolved subject/scope | Omit, with reason retained in the job ledger |

`not found`, `not documented`, `not observed`, and `source unavailable` map to
`UNKNOWN`, not `NEGATIVE_EXPLICIT`.

An explicit negative is still scoped. A manual stating that one firmware mode
does not support a protocol is not a universal product-level negative. A
`catalog_coverage.communication_protocols.complete` declaration is a separate
curation assertion with the limited Analyzer semantics documented by AVForge;
ingestion must not create it automatically merely because a source search was
exhaustive.

## 13. Measurement Semantics and False Precision

`semantic_precision` is one of:

- `exact`: the source gives an exact value in the stated context;
- `minimum`: a lower bound such as `>8 kOhm`;
- `maximum`: an upper bound such as `<100 ohm`;
- `range`: inclusive or source-defined minimum and maximum;
- `approximate`: the source uses approximately, about, nominally, or similar;
- `nominal`: the source labels a nominal value rather than a guaranteed limit;
- `not-rated`: the source explicitly says NR, N/R, or not recommended;
- `unknown`: no usable value was established.

Rules:

- `>8 kOhm` must not become exactly `8000 ohm`.
- `<100 ohm` must not become exactly `100 ohm`.
- `100-240 VAC` remains a range.
- `NR` is not zero, null, or a supported operating point.
- A shared current or capacity remains shared unless per-port scope is
  explicit.
- A generic marketing headline cannot override a load-, topology-, mode-, or
  model-specific table.
- Unit conversion is allowed only when the source value and conversion are
  exact and the original semantic qualifier is retained. Conversion is not a
  license to remove `minimum`, `maximum`, or `approximate`.
- If current Schema 3.8 cannot express the qualifier faithfully, the fact is
  `NOTES_ONLY`, `OMIT_UNKNOWN`, or a gap issue; it is not rounded into a
  misleading measurement.

## 14. Conflict Detection

Conflict comparison occurs only after identity, variant, subject, property,
unit, and condition scopes are normalized. A difference is not necessarily a
true conflict.

| Classification | Definition | Required action |
| --- | --- | --- |
| `TRUE_CONFLICT` | Same resolved subject/property/condition but incompatible values or claims | Preserve all evidence; do not select a canonical value automatically; escalate |
| `TERMINOLOGY_DIFFERENCE` | Different wording with the same engineering meaning | Normalize to one fact and retain both source terms |
| `PRECISION_DIFFERENCE` | One value is more or less precise without incompatible semantics | Preserve qualifiers; do not upgrade approximate to exact |
| `CONTEXT_DIFFERENCE` | Values apply to different loads, modes, interfaces, firmware, regions, or conditions | Keep separate conditioned facts |
| `REVISION_DIFFERENCE` | Values belong to different source or hardware revisions | Keep revision-scoped facts; resolve only with explicit identity/revision policy |
| `UNKNOWN_RELATIONSHIP` | The system cannot prove that two claims have the same scope | Do not merge; route for review if either would affect mapping |

No default rule chooses newest, largest, smallest, datasheet, manual, or
product page. A documented domain rule may resolve a conflict only when its
scope and rationale are explicit. Otherwise the issue contains both evidence
sets and blocks `READY` for the affected fact.

## 15. Mapping Contract

Each normalized fact receives exactly one primary mapping disposition:

| Disposition | Meaning |
| --- | --- |
| `STRUCTURED` | Current schema has a faithful field and required vocabulary IDs exist |
| `NOTES_ONLY` | Fact is useful but current structured fields would misrepresent it |
| `OMIT_UNKNOWN` | Fact is unknown, not applicable, or not material enough to store |
| `VOCAB_GAP` | Schema supports the concept but the required controlled ID is absent |
| `SCHEMA_GAP` | Current schema cannot represent an engineering-important fact faithfully |
| `CONFLICT` | A true unresolved conflict prevents a canonical mapping |

`NOTES_ONLY` is not permission to hide a blocking fact. The mapping plan must
state why the fact does not affect structural correctness or why review is
required. A shared USB power budget, conditional stream capacity, or license
state must not be placed in a per-port or unconditional field simply because
that field exists.

Mapping must use the current schema and vocabulary files at job execution
time. The mapping report records the schema version, vocabulary versions, and
file content hashes used for the decision.

Each fact ID may have only one primary mapping result, and every normalized
fact must have exactly one mapping result before the job can become `READY`.
Mappings to unknown fact IDs are invalid.

### Mapping v1 implementation contract

The deterministic Mapping v1 API consumes only a validated Fact Extraction v1
result. A completed `MappingResult` copies the extraction identity and fact
coverage, then assigns exactly one `MappingRecord` to every fact. A mapping
record retains the `fact_id` and all of that fact's `evidence_ids`; it may also
retain `conflict_ids` or a gap-proposal ID. Mapping does not decide whether a
source statement is true and does not generate an equipment record.

Targets are structured descriptors rooted at `equipment`. Their segments are
either named `property` segments or identity-based `entity` segments keyed by
`local_id` or `semantic_id`. Array indexes and executable expressions are not
valid targets. This permits future generation to address repeated interfaces
without making Mapping depend on fragile array positions.

The initial states are exactly `STRUCTURED`, `NOTES_ONLY`, `OMIT_UNKNOWN`,
`VOCAB_GAP`, `SCHEMA_GAP`, and `CONFLICT`. Deterministic validation requires a
target for `STRUCTURED` and `VOCAB_GAP`, a reason for `NOTES_ONLY`, unknown or
not-applicable semantics for `OMIT_UNKNOWN`, a proposal for each gap state, and
an unresolved extraction conflict for `CONFLICT`. A conflict blocks only the
facts that reference it; unrelated facts receive independent decisions.

Mapping and gap proposal IDs are derived from logical content, not timestamps,
filesystem paths, list positions, batch positions, or agent ordering. Existing
vocabulary IDs are loaded read-only and must be exact; a missing ID produces a
proposal rather than a fuzzy fallback or vocabulary mutation. Semantic
comparison distinguishes `NO_CHANGE`, `MAPPING_CHANGED`, vocabulary-gap and
schema-gap additions/removals, `CONFLICT_MAPPING_CHANGED`, and
`REVIEW_REQUIRED`, while ignoring result timestamps.

Mapping v1 does not infer a disposition from a fact property or source wording.
It validates an explicit deterministic decision. When a future planner has
multiple applicable dispositions, its documented precedence is `CONFLICT`,
`SCHEMA_GAP`, `VOCAB_GAP`, then `STRUCTURED`, `NOTES_ONLY`, and
`OMIT_UNKNOWN`; the selected result must still satisfy the state-specific
invariants. This ordering cannot select a source winner or repair a gap.

## 16. Vocabulary Gaps

`VOCAB_GAP` means all of the following are true:

1. An official fact identifies a connector, signal, protocol, unit, slot, or
   other vocabulary-controlled concept.
2. The current schema has a suitable field for that concept.
3. No current canonical vocabulary ID represents it faithfully.
4. An existing ID cannot be reused without changing meaning.

The ingestion job may create a proposal, never a vocabulary entry. A proposal
contains:

```json
{
  "vocabulary": "connectors",
  "proposed_id": "example-connector",
  "label": "Example connector",
  "meaning": "Physical connector as documented by the manufacturer",
  "evidence_refs": ["ev-001"],
  "why_existing_ids_are_insufficient": "...",
  "affected_records": ["candidate-only"],
  "approval": "REQUIRED"
}
```

The candidate record must not contain the unapproved ID. The job state includes
`VOCAB_GAP` until a human approves and a separate vocabulary change is made.

Mapping v1 serializes this proposal with the fact ID, evidence references,
vocabulary name, proposed identifier, meaning, and why existing IDs are
insufficient. It validates that the proposed identifier is not already a
canonical ID and never edits the vocabulary files.

## 17. Schema Gaps

`SCHEMA_GAP` means all of the following are true:

1. The equipment exposes a meaningful engineering fact.
2. The fact matters to catalog modeling, compatibility, safety, capacity, or
   future load/reporting behavior.
3. Current Schema 3.8 cannot represent it faithfully.
4. Notes-only treatment would materially reduce engineering correctness.

Schema gap examples may include a shared capacity budget, a condition set not
supported by current electrical variants, or a license-conditioned capability
whose availability must be machine-readable. A marketing feature, a cosmetic
detail, an unneeded implementation detail, or a fact already faithfully
preserved in notes is not automatically a schema gap.

A schema-gap issue contains the fact, evidence, attempted fields, why each
field is unsuitable, the engineering consequence of omission, and a proposed
minimal extension direction. Ingestion does not modify the schema or put a
new field in `extensions` merely to make validation pass. `SCHEMA_GAP` blocks
publication of that fact and normally blocks `READY` for the record.

Schema gaps and vocabulary gaps are independent. A missing vocabulary ID is
not evidence that the schema needs a new field; an unsuitable field is not
fixed by inventing a vocabulary ID.

Mapping v1 serializes a schema-gap proposal with the fact ID, evidence
references, engineering meaning, why the current schema is insufficient, the
semantics that would be lost, and the affected engineering area. The proposal
documents the gap only; it does not design or apply a schema extension.

## 18. Conditional Capabilities

The intermediate ledger preserves conditions as first-class data even when
Schema 3.8 cannot structure them:

```json
{
  "conditions": [
    { "kind": "license", "property": "installed_application", "operator": "equals", "value": "NVM-E1" },
    { "kind": "power_mode", "property": "mode", "operator": "equals", "value": "PoE+" }
  ]
}
```

Allowed condition kinds are open for source vocabulary but must be classified
as one of `license`, `installed_application`, `firmware`, `power_mode`,
`hardware_module`, `configuration`, or `operating_mode` when applicable.

Conditions are conjunctive within one fact. Alternative source-supported
conditions are separate facts or explicit alternatives; they must not be
flattened into the base capability. The mapper may emit a condition into a
current schema field only when that schema field has matching semantics. If
not, it emits `NOTES_ONLY` or `SCHEMA_GAP` and retains the full condition.

The job must distinguish:

- base hardware capability;
- possible modifier such as a license or module;
- configured instance state;
- future firmware claim.

Catalog records may use current `capability_modifiers` for supported possible
modifiers, but ingestion must not claim an effective installed configuration.

## 19. Draft Generation and Stable IDs

Draft generation is deterministic and consumes only a resolved identity and
facts with approved mapping dispositions. It uses current repository field
conventions and writes only under `equipment/<vendor>/`.

ID rules:

- Equipment ID: canonical lowercase manufacturer namespace plus normalized
  model, for example `qsys.nvm-302e`. The model normalization removes only
  presentation punctuation that the identity resolver explicitly records; it
  does not remove meaningful variant suffixes.
- Vendor directory: deterministic lowercase repository slug assigned by the
  resolved manufacturer identity.
- Interface ID: stable semantic role plus ordinal or manufacturer label,
  such as `hdmi-input-1`, `lan-a`, or `gpio-1`. IDs do not depend on array
  position alone.
- Signal ID: parent interface ID plus stable signal role, such as
  `hdmi-input-1-video`.
- Physical connector and point IDs: stable physical role and position, such as
  `gpio-terminal-block` and `gpio-pin-2`.
- Communication/capability IDs: stable functional role, not a prose label and
  not a generated hash.

If deterministic normalization would collide or identity evidence does not
provide a stable role, generation stops with `IDENTITY_AMBIGUOUS` or
`DRAFT_GENERATION_FAILED`. IDs are not invented to satisfy a schema error.

Generation must not:

- infer connector gender;
- infer protocols or signals from connector identity;
- infer signal compatibility from physical mating;
- infer runtime capacity from port count;
- create virtual bridge, parallel, or runtime interfaces;
- convert a possible license/module/firmware feature into base support;
- fill undocumented values with `0`, `null`, a typical industry value, or a
  neighboring model's value.

## 20. Validation Pipeline

The ingestion runner invokes, without redefining, these authoritative checks:

1. Parse every generated JSON document.
2. Validate against the current `schemas/equipment.schema.json`.
3. Invoke `validator/validate_semantics.py` with the candidate and the
   relevant catalog records.
4. Run the relevant existing unit tests.
5. Run Compatibility Analyzer regression tests using explicit requests and
   expected conservative results. The analyzer is not modified by ingestion.
6. Run full catalog semantic validation.
7. Run `git diff --check` on the candidate change.
8. Run a machine audit for ID uniqueness, internal references, source
   documentation, structured/notes dispositions, forbidden false precision,
   expected counts, and no virtual endpoints.

The runner records command, environment/interpreter, repository HEAD,
schema/vocabulary hashes, exit code, stdout/stderr references, and timestamp.
An absent test or unavailable validator is `VALIDATION_FAILED`, not a pass.
For a `READY` decision, validation results must be present and passing for
`json_parse`, `equipment_schema`, `semantic_validation`, `existing_tests`,
`compatibility_tests`, `catalog_validation`, `git_diff_check`, and
`machine_audit`.

## 21. Optional Equipment-Specific QA Probes

The framework may create temporary probes after mapping. A probe is a test
request, not catalog data and not a permanent compatibility assertion. Examples
include analog-audio output to analog-audio input, network-video transmitter to
receiver, or Dante transmitter to Dante receiver.

Probe generation is allowed only when both endpoints and the requested
function are explicitly represented. It may detect an obviously incomplete or
contradictory model, but it may not infer a new capability, add a known
compatibility, alter the analyzer, or turn a compatible result into a permanent
claim. Probe results are retained in the job report and expire with the job
unless separately approved as evidence.

## 22. Decision State Machine

Each job has one primary state and a list of zero or more issue objects. The
primary state is deterministic and ordered by blocking severity:

```text
VALIDATION_FAILED
SCHEMA_GAP
VOCAB_GAP
IDENTITY_AMBIGUOUS
SOURCE_NOT_FOUND
INSUFFICIENT_EVIDENCE
NEEDS_REVIEW
READY
```

`READY` requires:

- resolved exact identity;
- no unresolved true conflict affecting a mapped or required fact;
- no blocking vocabulary or schema gap;
- sufficient Tier 1/approved evidence for every structured engineering fact;
- no unsupported inference or false precision;
- structural, semantic, regression, catalog, and machine audits pass.
- every normalized fact has one mapping result and all evidence references
  resolve to acquired sources;
- every required validation result is present and passing.

`NEEDS_REVIEW` is used for a non-blocking human choice or policy decision
that does not fit a more specific state. It is not a confidence score. A job
may also have `pipeline_status: BLOCKED` while a future automated stage is not
implemented; that status is not a human-review issue and must not enter the
review queue unless a separate blocking issue exists.

`INSUFFICIENT_EVIDENCE` means the identity is adequate but an important fact
cannot be supported sufficiently. `SOURCE_NOT_FOUND` means identity is
adequate but no suitable official source was acquired. `IDENTITY_AMBIGUOUS`
means identity scope is unresolved. `VOCAB_GAP` and `SCHEMA_GAP` have the
definitions above. `VALIDATION_FAILED` takes precedence over all successful
mapping states.

Issue objects have `issue_id`, `code`, `severity`, `stage`, `subjects`,
`evidence_refs`, `message`, `blocking`, and `recommended_action`. A batch
summary counts primary states; it does not collapse multiple issues into a
single subjective score.

## 23. Human Review Queue

Review presents exceptions, not the full research narrative. Each issue view
contains:

- original intake item and resolved identity;
- affected subject/property and proposed JSON path;
- concise explanation of the decision;
- conflicting or supporting source references and locators;
- normalized values and qualifiers side by side;
- proposed structured/notes/omit/gap disposition;
- validation impact;
- explicit reviewer choices available;
- history of prior review decisions.

The reviewer may approve a source classification, choose between explicitly
resolved identities, approve a vocabulary proposal, approve a documented
domain conflict policy, or reject the candidate. The reviewer may not edit a
fact without attaching evidence or bypass deterministic validation.

For a batch of 100 items, only jobs with blocking issues or an explicit sample
policy enter manual review. A clean `READY` job still requires the separate
publication approval described below.

## 24. Publication Boundary

Ingestion success and publication are separate states.

Version 1 requires explicit publication approval. `READY` means a candidate is
eligible for publication; it does not stage, commit, or push it. A publication
operation must:

1. re-check repository HEAD and worktree policy;
2. verify that only explicitly approved candidate paths are changed;
3. rerun the final validation against the publication tree;
4. stage only approved paths;
5. show staged name/status/stat/check output to the operator;
6. require an explicit commit action;
7. require a separate explicit push action.

A candidate must never overwrite an existing record automatically. A future
batch publication policy may permit automation only after separate governance
approval and must retain the same path allowlist and validation gates.

## 25. Reruns and Idempotency

The job identity is based on intake item plus resolved identity scope. A rerun
loads the previous job and compares:

- resolved identity;
- source IDs, final URLs, revisions, and content hashes;
- normalized facts and conditions;
- mapping decisions;
- generated candidate bytes;
- validation results.

Rerun outcomes are:

- `NO_CHANGE`: same identity, source hashes, facts, mapping, and candidate;
- `SOURCE_UPDATED`: source content or revision changed but normalized facts did
  not change;
- `FACTS_CHANGED`: normalized facts or conditions changed;
- `REVIEW_REQUIRED`: identity, conflict, gap, or mapping scope changed in a way
  that cannot be safely compared.

The prior candidate is preserved for comparison. A rerun does not overwrite a
published record or silently reset a human decision. Changed evidence
invalidates only the affected fact decisions and any dependent validation.

## 26. Runtime and Tracked Artifacts

The minimal future layout is:

```text
ingestion/
  README.md
  contracts/
  jobs/
  cache/
  reports/
```

Only contracts and stable documentation belong in version control initially.
Runtime job manifests, acquired binaries, extracted text, temporary drafts,
logs, reports, and Mapping v1 results under `.ingestion/mappings/` are runtime artifacts and should be ignored by a future
implementation-specific `.gitignore` policy. This contract document does not
create those directories.

A job manifest must reference the intake hash, repository HEAD, source hashes,
fact ledger, mapping plan, validation results, issue list, state, and review
history. Artifact references must be content-addressed or otherwise immutable.
It also records `pipeline_status`, independent of the primary curation state,
with one of `PENDING`, `RUNNING`, `BLOCKED`, `FAILED`, or `COMPLETED`.

## 27. Batch Operation and Resumability

Each intake item receives an independent job and independent state. A batch
runner continues after an item failure and produces:

```text
total
READY
NEEDS_REVIEW
VOCAB_GAP
SCHEMA_GAP
INSUFFICIENT_EVIDENCE
SOURCE_NOT_FOUND
IDENTITY_AMBIGUOUS
VALIDATION_FAILED
```

The summary also reports source-acquisition failures and canceled items. A
resume operation selects incomplete or explicitly requested jobs by job key.
Completed jobs are not rerun unless source hashes, identity inputs, schema or
vocabulary hashes, or the requested contract version changed.

One item cannot cause another item's candidate, evidence, or state to be
discarded. Batch publication is an explicit allowlist of individually approved
jobs, not an implicit consequence of a successful batch.

## 28. Agent and Deterministic Responsibilities

An LLM or other agent may assist with:

- source discovery suggestions;
- document and section classification;
- locating candidate facts and locators;
- terminology normalization proposals;
- mapping proposals;
- explaining conflicts and review issues;
- proposing temporary QA probes.

An agent output is untrusted input to the next stage. It must include source
references for every proposed fact and may not create an evidence-free fact.

Deterministic code owns:

- intake parsing and duplicate handling;
- identity candidate comparison and state aggregation;
- source metadata and content-hash checks;
- fact/unit/qualifier shape checks;
- vocabulary existence and canonical-ID checks;
- stable ID generation and collision detection;
- JSON generation;
- JSON Schema validation;
- semantic validation invocation;
- unit, analyzer, catalog, and machine-audit execution;
- issue severity and primary state aggregation;
- staged path allowlists and publication safeguards.

No agent can override a deterministic failure, convert `UNKNOWN` to negative,
approve a vocabulary/schema gap, or authorize publication.

## 29. Security and Robustness

Source documents and web pages are untrusted data. The acquisition and
extraction implementation must:

- isolate source parsing from publication credentials and repository writes;
- reject or sandbox active content and unexpected file types;
- limit redirects, size, decompression, and extraction time;
- record the final URL and every redirect relevant to provenance;
- detect duplicate content by hash;
- retain content hashes when a remote source later changes;
- treat PDF/HTML instructions, hidden text, comments, metadata, and prompt-like
  content as data only;
- never execute source-provided code or commands;
- never expose credentials, local paths, or unrelated job artifacts to source
  content or an agent;
- mark broken, partial, password-protected, OCR-only, and unreadable sources;
- require human review for a source that changes identity scope or canonical
  classification.

Prompt injection inside a manufacturer document, reseller page, search result,
or extracted text cannot change the job contract. It cannot tell the system to
ignore conflicts, declare support, modify schema/vocabulary, or publish.

## 30. NVM-302E Acceptance Test

NVM-302E is not ingested by this architecture task. It is the first future
acceptance input and must be processed by the generic pipeline without
manufacturer/model-specific code or prompt rules.

The acceptance fixture will provide only the generic intake item and the
discovered official sources. The test evaluates the job artifacts and decision
state, not whether a hardcoded expected JSON is reproduced.

The framework must independently preserve evidence and surface review issues
for at least:

- two HDMI physical inputs;
- encode behavior conditioned by NVM-E1 and NVM-E2;
- application/license distinction;
- Mediacast semantics;
- PoE modes;
- shared USB power conditioned by PoE mode;
- USB-C host/device and DP Alt Mode;
- future-firmware AV Bridging claim.

The acceptance criteria are:

- physical HDMI inputs are not inferred to imply a network-video protocol;
- NVM-E1/NVM-E2 and application/license conditions remain explicit;
- Mediacast is not flattened into an unsupported generic capability;
- PoE modes and shared USB power are not represented as unconditional or
  per-port values without evidence;
- USB-C roles and DP Alt Mode remain separate documented conditions;
- future-firmware claims are not current support;
- schema/vocabulary gaps are reported instead of shoehorned;
- all source locators and conflicts survive into the job report;
- the resulting primary state and issue list are deterministic.

## 31. Contract Review Checklist

Before implementation begins, reviewers must confirm:

- every stage has an input, output, responsibility, prohibition, and failure
  mode;
- identity is resolved before facts are merged;
- search snippets and third-party sources cannot silently become canonical;
- every structured fact has provenance;
- bounds, ranges, approximate values, NR, and conditions survive mapping;
- negative facts require explicit scoped evidence;
- vocabulary and schema gaps have separate workflows;
- existing schema, semantic validator, analyzer, and catalog coverage rules are
  invoked rather than reimplemented;
- agent output cannot bypass deterministic validation;
- publication is explicit and separate from ingestion success;
- reruns preserve historical evidence and do not overwrite records silently;
- batch failures are isolated and resumable;
- no NVM-302E-specific branch, prompt, parser, or expected-answer fixture is
  required by the generic contract.

The contract is intentionally implementation-ready but leaves transport,
cache technology, OCR library, agent provider, and job storage implementation
choices open. Those choices must not change the normative semantics above.
